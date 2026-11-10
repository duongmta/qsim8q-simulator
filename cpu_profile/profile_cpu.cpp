#include "qsim_cpu.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <complex>
#include <cstddef>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace {

using Clock = std::chrono::steady_clock;
using qsim8_cpu::Amplitude;
using qsim8_cpu::Circuit;
using qsim8_cpu::Gate;

volatile double g_numeric_sink = 0.0;
volatile std::uint64_t g_integer_sink = 0;

struct Options {
    std::string input;
    std::string raw_output;
    std::string validation_output;
    int samples = 20;
    int warmup = 3;
    double min_batch_ms = 5.0;
    int affinity_cpu = 4;
};

std::vector<std::string> split_tab(const std::string& line) {
    std::vector<std::string> fields;
    std::size_t begin = 0;
    while (true) {
        const std::size_t end = line.find('\t', begin);
        fields.push_back(line.substr(begin, end - begin));
        if (end == std::string::npos) break;
        begin = end + 1;
    }
    return fields;
}

std::vector<Circuit> read_suite(const std::string& path) {
    std::ifstream stream(path);
    if (!stream) throw std::runtime_error("Cannot open input suite: " + path);

    std::vector<Circuit> circuits;
    Circuit current{};
    bool inside = false;
    std::string line;
    int line_number = 0;
    while (std::getline(stream, line)) {
        ++line_number;
        if (line.empty() || line[0] == '#') continue;
        const std::vector<std::string> fields = split_tab(line);
        try {
            if (fields[0] == "CASE") {
                if (inside || fields.size() != 6)
                    throw std::runtime_error("Malformed CASE record");
                current = Circuit{};
                current.id = fields[1];
                current.suite = fields[2];
                current.num_qubits = std::stoi(fields[3]);
                current.depth = std::stoi(fields[4]);
                current.gates.reserve(static_cast<std::size_t>(std::stoi(fields[5])));
                inside = true;
            } else if (fields[0] == "GATE") {
                if (!inside || fields.size() != 5)
                    throw std::runtime_error("Malformed GATE record");
                current.gates.push_back(qsim8_cpu::make_gate(
                    qsim8_cpu::gate_from_name(fields[1]), std::stoi(fields[2]),
                    std::stoi(fields[3]), std::stof(fields[4])));
            } else if (fields[0] == "REF") {
                if (!inside || fields.size() != 3)
                    throw std::runtime_error("Malformed REF record");
                current.expected.emplace_back(std::stod(fields[1]),
                                               std::stod(fields[2]));
            } else if (fields[0] == "END") {
                if (!inside) throw std::runtime_error("END outside CASE");
                const std::size_t expected_size = std::size_t{1} << current.num_qubits;
                if (current.expected.size() != expected_size)
                    throw std::runtime_error("Reference statevector has wrong size");
                circuits.push_back(std::move(current));
                inside = false;
            } else {
                throw std::runtime_error("Unknown record type");
            }
        } catch (const std::exception& exc) {
            throw std::runtime_error(path + ":" + std::to_string(line_number) +
                                     ": " + exc.what());
        }
    }
    if (inside) throw std::runtime_error("Input suite ends inside a CASE");
    return circuits;
}

Options parse_options(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        auto value = [&]() -> std::string {
            if (++i >= argc) throw std::invalid_argument("Missing value for " + arg);
            return argv[i];
        };
        if (arg == "--input") options.input = value();
        else if (arg == "--raw-output") options.raw_output = value();
        else if (arg == "--validation-output") options.validation_output = value();
        else if (arg == "--samples") options.samples = std::stoi(value());
        else if (arg == "--warmup") options.warmup = std::stoi(value());
        else if (arg == "--min-batch-ms") options.min_batch_ms = std::stod(value());
        else if (arg == "--affinity-cpu") options.affinity_cpu = std::stoi(value());
        else throw std::invalid_argument("Unknown option: " + arg);
    }
    if (options.input.empty() || options.raw_output.empty() ||
        options.validation_output.empty())
        throw std::invalid_argument("--input, --raw-output and --validation-output are required");
    if (options.samples < 1 || options.warmup < 0 || options.min_batch_ms <= 0.0)
        throw std::invalid_argument("Invalid measurement configuration");
    return options;
}

void configure_process(const Options& options) {
#if defined(_WIN32)
    if (options.affinity_cpu >= 0) {
        if (options.affinity_cpu >= static_cast<int>(sizeof(DWORD_PTR) * 8))
            throw std::invalid_argument("affinity CPU is outside the process mask width");
        const DWORD_PTR mask = DWORD_PTR{1} << options.affinity_cpu;
        if (!SetProcessAffinityMask(GetCurrentProcess(), mask))
            throw std::runtime_error("SetProcessAffinityMask failed: " +
                                     std::to_string(GetLastError()));
    }
    SetPriorityClass(GetCurrentProcess(), ABOVE_NORMAL_PRIORITY_CLASS);
#else
    (void)options;
#endif
}

template <typename Function>
std::pair<std::uint64_t, double> timed(std::uint64_t repetitions,
                                       Function&& function) {
    const auto start = Clock::now();
    function(repetitions);
    const auto stop = Clock::now();
    const double ns = std::chrono::duration<double, std::nano>(stop - start).count();
    return {repetitions, ns};
}

template <typename Function, typename Prepare>
std::uint64_t calibrate(double min_batch_ms, Function&& function,
                        Prepare&& prepare) {
    constexpr std::uint64_t kMaxRepetitions = 100000000ULL;
    const double target_ns = min_batch_ms * 1.0e6;
    std::uint64_t repetitions = 1;
    while (true) {
        prepare();
        const auto result = timed(repetitions, function);
        if (result.second >= target_ns || repetitions >= kMaxRepetitions)
            return repetitions;
        const double ratio = target_ns / std::max(result.second, 1.0);
        const double factor = std::min(10.0, std::max(2.0, ratio * 1.15));
        repetitions = std::min(
            kMaxRepetitions,
            static_cast<std::uint64_t>(std::ceil(repetitions * factor)));
    }
}

template <typename Function, typename Prepare>
void measure_phase(std::ofstream& raw, const Circuit& circuit,
                   const std::string& phase, int samples, int warmup,
                   double min_batch_ms, Function&& function,
                   Prepare&& prepare) {
    const std::uint64_t repetitions = calibrate(min_batch_ms, function, prepare);
    for (int i = 0; i < warmup; ++i) {
        prepare();
        function(repetitions);
    }
    for (int sample = 0; sample < samples; ++sample) {
        prepare();
        const auto result = timed(repetitions, function);
        const double ns_per_run = result.second / static_cast<double>(result.first);
        raw << circuit.id << ',' << circuit.suite << ',' << circuit.num_qubits
            << ',' << circuit.depth << ',' << circuit.gates.size() << ','
            << phase << ',' << sample << ',' << result.first << ','
            << std::setprecision(17) << result.second << ',' << ns_per_run
            << ',' << g_numeric_sink << ',' << g_integer_sink << '\n';
    }
}

void validate(const Circuit& circuit, std::ofstream& output) {
    std::vector<Amplitude> actual(std::size_t{1} << circuit.num_qubits);
    qsim8_cpu::reset_zero_state(actual);
    qsim8_cpu::execute_circuit(actual, circuit.gates);

    double actual_norm2 = 0.0;
    double reference_norm2 = 0.0;
    std::complex<double> overlap(0.0, 0.0);
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const std::complex<double> a(actual[i].real(), actual[i].imag());
        actual_norm2 += std::norm(a);
        reference_norm2 += std::norm(circuit.expected[i]);
        overlap += std::conj(circuit.expected[i]) * a;
    }
    const double phase = std::abs(overlap) > 1e-15 ? std::arg(overlap) : 0.0;
    const std::complex<double> correction = std::polar(1.0, -phase);
    double max_error = 0.0;
    for (std::size_t i = 0; i < actual.size(); ++i) {
        const std::complex<double> aligned =
            std::complex<double>(actual[i].real(), actual[i].imag()) * correction;
        max_error = std::max(max_error, std::abs(aligned - circuit.expected[i]));
    }
    const double fidelity = actual_norm2 > 0.0 && reference_norm2 > 0.0
        ? std::min(1.0, std::norm(overlap) / (actual_norm2 * reference_norm2))
        : 0.0;
    const double norm_error = std::abs(actual_norm2 - 1.0);
    const bool passed = max_error <= 1e-5 && fidelity >= 1.0 - 1e-7 &&
                        norm_error <= 1e-5;
    output << circuit.id << ',' << std::setprecision(17) << max_error << ','
           << fidelity << ',' << norm_error << ',' << (passed ? "PASS" : "FAIL")
           << '\n';
}

void profile(const Circuit& circuit, const Options& options, std::ofstream& raw) {
    const std::size_t size = std::size_t{1} << circuit.num_qubits;
    std::vector<Amplitude> dense(size), state(size), destination(size);
    qsim8_cpu::make_dense_state(dense);
    state = dense;

    std::vector<Gate> one_q;
    std::vector<Gate> two_q;
    for (const Gate& gate : circuit.gates) {
        (qsim8_cpu::is_two_qubit(gate.type) ? two_q : one_q).push_back(gate);
    }

    auto reset_phase = [&](std::uint64_t repetitions) {
        for (std::uint64_t i = 0; i < repetitions; ++i)
            qsim8_cpu::reset_zero_state(state);
        g_numeric_sink += qsim8_cpu::state_checksum(state) * 1e-300;
    };
    auto copy_phase = [&](std::uint64_t repetitions) {
        for (std::uint64_t i = 0; i < repetitions; ++i)
            qsim8_cpu::copy_state(dense, destination);
        g_numeric_sink += qsim8_cpu::state_checksum(destination) * 1e-300;
    };
    auto dispatch_phase = [&](std::uint64_t repetitions) {
        std::uint64_t checksum = 0;
        for (std::uint64_t i = 0; i < repetitions; ++i)
            checksum ^= qsim8_cpu::dispatch_checksum(circuit.gates) + i;
        g_integer_sink ^= checksum;
    };
    auto one_q_phase = [&](std::uint64_t repetitions) {
        for (std::uint64_t i = 0; i < repetitions; ++i)
            qsim8_cpu::execute_circuit(state, one_q);
        g_numeric_sink += qsim8_cpu::state_checksum(state) * 1e-300;
    };
    auto two_q_phase = [&](std::uint64_t repetitions) {
        for (std::uint64_t i = 0; i < repetitions; ++i)
            qsim8_cpu::execute_circuit(state, two_q);
        g_numeric_sink += qsim8_cpu::state_checksum(state) * 1e-300;
    };
    auto execute_phase = [&](std::uint64_t repetitions) {
        for (std::uint64_t i = 0; i < repetitions; ++i)
            qsim8_cpu::execute_circuit(state, circuit.gates);
        g_numeric_sink += qsim8_cpu::state_checksum(state) * 1e-300;
    };

    auto no_prepare = []() {};
    auto prepare_state = [&]() { state = dense; };

    measure_phase(raw, circuit, "reset", options.samples, options.warmup,
                  options.min_batch_ms, reset_phase, no_prepare);
    measure_phase(raw, circuit, "copy", options.samples, options.warmup,
                  options.min_batch_ms, copy_phase, no_prepare);
    measure_phase(raw, circuit, "dispatch", options.samples, options.warmup,
                  options.min_batch_ms, dispatch_phase, no_prepare);
    if (!one_q.empty())
        measure_phase(raw, circuit, "kernel_1q", options.samples, options.warmup,
                      options.min_batch_ms, one_q_phase, prepare_state);
    if (!two_q.empty())
        measure_phase(raw, circuit, "kernel_2q", options.samples, options.warmup,
                      options.min_batch_ms, two_q_phase, prepare_state);
    measure_phase(raw, circuit, "execute", options.samples, options.warmup,
                  options.min_batch_ms, execute_phase, prepare_state);
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parse_options(argc, argv);
        configure_process(options);
        const std::vector<Circuit> circuits = read_suite(options.input);
        std::ofstream raw(options.raw_output);
        std::ofstream validation(options.validation_output);
        if (!raw || !validation) throw std::runtime_error("Cannot create output CSV");
        raw << "case_id,suite,num_qubits,depth,native_instructions,phase,sample,"
               "batch_repetitions,total_ns,ns_per_run,numeric_sink,integer_sink\n";
        validation << "case_id,max_error,fidelity,norm_error,status\n";

        std::cout << "QSim8 CPU FP32 profiler: " << circuits.size()
                  << " cases, " << options.samples << " samples/case, CPU affinity "
                  << options.affinity_cpu << "\n";
        for (std::size_t i = 0; i < circuits.size(); ++i) {
            validate(circuits[i], validation);
            profile(circuits[i], options, raw);
            std::cout << "[" << (i + 1) << "/" << circuits.size() << "] "
                      << circuits[i].id << '\n';
        }
        std::cout << "CPU profiling completed.\n";
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "ERROR: " << exc.what() << '\n';
        return 1;
    }
}
