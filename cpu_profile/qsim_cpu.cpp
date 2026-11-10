#include "qsim_cpu.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <stdexcept>

#if defined(_MSC_VER)
#define QSIM_NOINLINE __declspec(noinline)
#elif defined(__GNUC__) || defined(__clang__)
#define QSIM_NOINLINE __attribute__((noinline))
#else
#define QSIM_NOINLINE
#endif

namespace qsim8_cpu {
namespace {

constexpr float kInvSqrt2 = 0.70710678118654752440f;

}  // namespace

Gate make_gate(GateType type, int target, int control, float theta) {
    Gate gate{type, target, control, theta, 0.0f, 0.0f};
    if (type == GateType::RX || type == GateType::RY ||
        type == GateType::RZ) {
        const float half = theta * 0.5f;
        gate.p0 = std::cos(half);
        gate.p1 = std::sin(half);
    }
    return gate;
}

GateType gate_from_name(const std::string& name) {
    if (name == "H") return GateType::H;
    if (name == "X") return GateType::X;
    if (name == "Y") return GateType::Y;
    if (name == "Z") return GateType::Z;
    if (name == "S") return GateType::S;
    if (name == "T") return GateType::T;
    if (name == "RX") return GateType::RX;
    if (name == "RY") return GateType::RY;
    if (name == "RZ") return GateType::RZ;
    if (name == "CNOT") return GateType::CNOT;
    if (name == "CZ") return GateType::CZ;
    throw std::invalid_argument("Unsupported gate: " + name);
}

const char* gate_name(GateType type) {
    switch (type) {
    case GateType::H: return "H";
    case GateType::X: return "X";
    case GateType::Y: return "Y";
    case GateType::Z: return "Z";
    case GateType::S: return "S";
    case GateType::T: return "T";
    case GateType::RX: return "RX";
    case GateType::RY: return "RY";
    case GateType::RZ: return "RZ";
    case GateType::CNOT: return "CNOT";
    case GateType::CZ: return "CZ";
    }
    return "UNKNOWN";
}

bool is_two_qubit(GateType type) {
    return type == GateType::CNOT || type == GateType::CZ;
}

QSIM_NOINLINE void reset_zero_state(std::vector<Amplitude>& state) {
    std::fill(state.begin(), state.end(), Amplitude(0.0f, 0.0f));
    if (!state.empty()) state[0] = Amplitude(1.0f, 0.0f);
}

QSIM_NOINLINE void copy_state(const std::vector<Amplitude>& source,
                              std::vector<Amplitude>& destination) {
    std::copy(source.begin(), source.end(), destination.begin());
}

void make_dense_state(std::vector<Amplitude>& state) {
    double norm2 = 0.0;
    for (std::size_t i = 0; i < state.size(); ++i) {
        const float re = std::sin(0.173f * static_cast<float>(i + 1));
        const float im = std::cos(0.119f * static_cast<float>(i + 1));
        state[i] = Amplitude(re, im);
        norm2 += static_cast<double>(re) * re + static_cast<double>(im) * im;
    }
    const float scale = static_cast<float>(1.0 / std::sqrt(norm2));
    for (Amplitude& value : state) value *= scale;
}

QSIM_NOINLINE void apply_single_qubit_gate(std::vector<Amplitude>& state,
                                            const Gate& gate) {
    const int nstates = static_cast<int>(state.size());
    const int stride = 1 << gate.target;
    const int block = stride << 1;

    for (int base = 0; base < nstates; base += block) {
        for (int offset = 0; offset < stride; ++offset) {
            const int i0 = base + offset;
            const int i1 = i0 + stride;
            const float ar = state[i0].real();
            const float ai = state[i0].imag();
            const float br = state[i1].real();
            const float bi = state[i1].imag();
            float o0r = ar, o0i = ai, o1r = br, o1i = bi;

            switch (gate.type) {
            case GateType::H:
                o0r = kInvSqrt2 * (ar + br);
                o0i = kInvSqrt2 * (ai + bi);
                o1r = kInvSqrt2 * (ar - br);
                o1i = kInvSqrt2 * (ai - bi);
                break;
            case GateType::X:
                o0r = br; o0i = bi; o1r = ar; o1i = ai;
                break;
            case GateType::Y:
                o0r = bi; o0i = -br; o1r = -ai; o1i = ar;
                break;
            case GateType::Z:
                o1r = -br; o1i = -bi;
                break;
            case GateType::S:
                o1r = -bi; o1i = br;
                break;
            case GateType::T:
                o1r = kInvSqrt2 * (br - bi);
                o1i = kInvSqrt2 * (br + bi);
                break;
            case GateType::RX:
                o0r = gate.p0 * ar + gate.p1 * bi;
                o0i = gate.p0 * ai - gate.p1 * br;
                o1r = gate.p1 * ai + gate.p0 * br;
                o1i = -gate.p1 * ar + gate.p0 * bi;
                break;
            case GateType::RY:
                o0r = gate.p0 * ar - gate.p1 * br;
                o0i = gate.p0 * ai - gate.p1 * bi;
                o1r = gate.p1 * ar + gate.p0 * br;
                o1i = gate.p1 * ai + gate.p0 * bi;
                break;
            case GateType::RZ:
                o0r = gate.p0 * ar + gate.p1 * ai;
                o0i = gate.p0 * ai - gate.p1 * ar;
                o1r = gate.p0 * br - gate.p1 * bi;
                o1i = gate.p1 * br + gate.p0 * bi;
                break;
            default:
                throw std::logic_error("Two-qubit gate sent to 1Q kernel");
            }
            state[i0] = Amplitude(o0r, o0i);
            state[i1] = Amplitude(o1r, o1i);
        }
    }
}

QSIM_NOINLINE void apply_two_qubit_gate(std::vector<Amplitude>& state,
                                         const Gate& gate) {
    const int nstates = static_cast<int>(state.size());
    const int control_mask = 1 << gate.control;
    const int target_mask = 1 << gate.target;

    if (gate.type == GateType::CNOT) {
        for (int i = 0; i < nstates; ++i) {
            if ((i & control_mask) != 0 && (i & target_mask) == 0) {
                std::swap(state[i], state[i | target_mask]);
            }
        }
    } else if (gate.type == GateType::CZ) {
        for (int i = 0; i < nstates; ++i) {
            if ((i & control_mask) != 0 && (i & target_mask) != 0) {
                state[i] = -state[i];
            }
        }
    } else {
        throw std::logic_error("One-qubit gate sent to 2Q kernel");
    }
}

QSIM_NOINLINE void execute_circuit(std::vector<Amplitude>& state,
                                   const std::vector<Gate>& gates) {
    for (const Gate& gate : gates) {
        if (is_two_qubit(gate.type)) {
            apply_two_qubit_gate(state, gate);
        } else {
            apply_single_qubit_gate(state, gate);
        }
    }
}

QSIM_NOINLINE std::uint64_t dispatch_checksum(
    const std::vector<Gate>& gates) {
    std::uint64_t value = 0;
    for (const Gate& gate : gates) {
        // Mirror the route decision in execute_circuit without performing the
        // state-vector kernel. The returned value keeps this loop observable.
        value += is_two_qubit(gate.type) ? 2ULL : 1ULL;
        value += static_cast<std::uint64_t>(gate.target + 1);
        value += static_cast<std::uint64_t>(gate.control + 2);
    }
    return value;
}

double state_checksum(const std::vector<Amplitude>& state) {
    double value = 0.0;
    for (std::size_t i = 0; i < state.size(); ++i) {
        value += (i + 1.0) * (static_cast<double>(state[i].real()) +
                              0.5 * static_cast<double>(state[i].imag()));
    }
    return value;
}

}  // namespace qsim8_cpu
