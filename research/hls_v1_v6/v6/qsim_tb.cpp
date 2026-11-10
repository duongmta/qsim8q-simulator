#include <algorithm>
#include <cmath>
#include <complex>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "qsim_hls.h"

// ============================================================================
// STANDARD HLS VALIDATION TESTBENCH
// Used unchanged for V1 -> V6 so all HLS architecture versions are evaluated
// with the same functional workload.
//
// This suite follows the final project specification:
//   - 18 tests
//   - 1..8 qubits
//   - H, X, Y, Z, S, T, RX, RY, RZ, CNOT, CZ
//   - SWAP decomposed into three CNOT instructions
//   - deterministic depth-20 mixed circuit at 8 qubits
//
// CPU/Qiskit reference policy:
//   - gate angles are rounded/stored as FP32
//   - HLS implementation remains Q2.30 fixed-point
//   - acceptance:
//       max amplitude error <= 1e-2
//       fidelity            >= 0.99
//       normalization error <= 1e-2
// ============================================================================

static const float PI_F = 3.14159265358979323846f;

static const double EMAX_LIMIT = 1e-2;
static const double FIDELITY_LIMIT = 0.99;
static const double NORM_ERROR_LIMIT = 1e-2;

typedef std::complex<float> RefComplex;

struct HostGate {
    GateType type;
    int target;
    int control;
    float theta;
};

struct TestCase {
    std::string id;
    int num_qubits;
    std::string description;
    std::vector<HostGate> gates;
};

static HostGate one_q(GateType type, int target, float theta = 0.0f) {
    HostGate g;
    g.type = type;
    g.target = target;
    g.control = INVALID_QUBIT;
    g.theta = theta;
    return g;
}

static HostGate two_q(GateType type, int control, int target) {
    HostGate g;
    g.type = type;
    g.target = target;
    g.control = control;
    g.theta = 0.0f;
    return g;
}

// Match the current FP32 CPU/Qiskit validation policy:
// first compute rotation parameters in single precision, then quantize them
// into the Q2.30 fields sent to the HLS core.
static instruction_word_t encode_host_gate(const HostGate& g) {
    q_real_t p0 = q_real_t(0);
    q_real_t p1 = q_real_t(0);

    if (g.type == GATE_RX || g.type == GATE_RY || g.type == GATE_RZ) {
        const float half = g.theta * 0.5f;
        const float c = std::cos(half);
        const float s = std::sin(half);
        p0 = q_real_t(c);
        p1 = q_real_t(s);
    }

    return encode_instruction(
        g.type,
        static_cast<uint8_t>(g.target),
        static_cast<uint8_t>(g.control),
        p0,
        p1
    );
}

// ----------------------------------------------------------------------------
// FP32 functional reference.
//
// This mirrors quantum_simulator.cpp mathematically, but is kept inside the
// HLS testbench so Vitis C Simulation / C-RTL Co-simulation remain self
// contained.
// ----------------------------------------------------------------------------
static void apply_reference_gate(
    std::vector<RefComplex>& state,
    int num_qubits,
    const HostGate& g) {

    const int nstates = 1 << num_qubits;

    if (g.type == GATE_CNOT || g.type == GATE_CZ) {
        const int control_mask = 1 << g.control;
        const int target_mask = 1 << g.target;

        for (int i = 0; i < nstates; ++i) {
            const bool control_is_1 = (i & control_mask) != 0;
            const bool target_is_0 = (i & target_mask) == 0;

            if (g.type == GATE_CNOT) {
                if (control_is_1 && target_is_0) {
                    const int j = i | target_mask;
                    std::swap(state[i], state[j]);
                }
            } else {
                const bool target_is_1 = (i & target_mask) != 0;
                if (control_is_1 && target_is_1) {
                    state[i] = -state[i];
                }
            }
        }
        return;
    }

    const int stride = 1 << g.target;
    const int block = stride << 1;

    const float inv_sqrt2 = 1.0f / std::sqrt(2.0f);
    const float half = g.theta * 0.5f;
    const float c = std::cos(half);
    const float s = std::sin(half);
    const RefComplex I(0.0f, 1.0f);

    for (int base = 0; base < nstates; base += block) {
        for (int offset = 0; offset < stride; ++offset) {
            const int i0 = base + offset;
            const int i1 = i0 + stride;

            const RefComplex a = state[i0];
            const RefComplex b = state[i1];

            RefComplex o0 = a;
            RefComplex o1 = b;

            switch (g.type) {
            case GATE_I:
                break;

            case GATE_H:
                o0 = inv_sqrt2 * (a + b);
                o1 = inv_sqrt2 * (a - b);
                break;

            case GATE_X:
                o0 = b;
                o1 = a;
                break;

            case GATE_Y:
                o0 = -I * b;
                o1 = I * a;
                break;

            case GATE_Z:
                o1 = -b;
                break;

            case GATE_S:
                o1 = I * b;
                break;

            case GATE_T:
                o1 = RefComplex(inv_sqrt2, inv_sqrt2) * b;
                break;

            case GATE_RX:
                o0 = c * a - I * s * b;
                o1 = -I * s * a + c * b;
                break;

            case GATE_RY:
                o0 = c * a - s * b;
                o1 = s * a + c * b;
                break;

            case GATE_RZ:
                o0 = RefComplex(c, -s) * a;
                o1 = RefComplex(c,  s) * b;
                break;

            default:
                throw std::runtime_error("Unsupported gate in reference model");
            }

            state[i0] = o0;
            state[i1] = o1;
        }
    }
}

// Exact deterministic deep-circuit generator used by the current
// quantum_validation.cpp and validate_all_with_qiskit.py.
static std::vector<HostGate> build_deep_mixed_circuit(int n, int depth) {
    if (n < 2) {
        throw std::invalid_argument(
            "deep mixed circuit requires at least 2 qubits"
        );
    }

    std::vector<HostGate> circuit;
    circuit.reserve(static_cast<std::size_t>(depth));

    for (int k = 0; k < depth; ++k) {
        const int mode = k % 11;
        const int q_a = (3 * k + 1) % n;
        const int q_b = (5 * k + 2) % n;
        const int q_c = (7 * k + 3) % n;

        switch (mode) {
        case 0:
            circuit.push_back(one_q(GATE_H, q_a));
            break;

        case 1:
            circuit.push_back(one_q(GATE_S, q_b));
            break;

        case 2:
            circuit.push_back(one_q(GATE_T, q_c));
            break;

        case 3:
            circuit.push_back(one_q(
                GATE_RX,
                q_a,
                static_cast<float>(0.07 * (k + 1))
            ));
            break;

        case 4:
            circuit.push_back(one_q(
                GATE_RY,
                q_b,
                static_cast<float>(-0.05 * (k + 1))
            ));
            break;

        case 5:
            circuit.push_back(one_q(
                GATE_RZ,
                q_c,
                static_cast<float>(0.03 * (k + 1))
            ));
            break;

        case 6:
            circuit.push_back(one_q(GATE_X, q_a));
            break;

        case 7:
            circuit.push_back(one_q(GATE_Y, q_b));
            break;

        case 8:
            circuit.push_back(one_q(GATE_Z, q_c));
            break;

        case 9: {
            const int control = (3 * k + 1) % n;
            int target = (control + 1 + (k % (n - 1))) % n;
            if (target == control) {
                target = (target + 1) % n;
            }
            circuit.push_back(two_q(GATE_CNOT, control, target));
            break;
        }

        case 10: {
            const int control = (5 * k + 2) % n;
            int target = (control + 1 + ((2 * k) % (n - 1))) % n;
            if (target == control) {
                target = (target + 1) % n;
            }
            circuit.push_back(two_q(GATE_CZ, control, target));
            break;
        }

        default:
            throw std::logic_error("unreachable gate mode");
        }
    }

    return circuit;
}

static std::vector<TestCase> build_tests() {
    std::vector<TestCase> tests;

    tests.push_back({"T01_X_1Q", 1, "X|0> -> |1>",
                     {one_q(GATE_X, 0)}});
    tests.push_back({"T02_H_1Q", 1, "H|0> superposition",
                     {one_q(GATE_H, 0)}});
    tests.push_back({"T03_Y_1Q", 1, "Y|0> -> i|1>",
                     {one_q(GATE_Y, 0)}});
    tests.push_back({"T04_HZ_1Q", 1, "H then Z: relative phase",
                     {one_q(GATE_H, 0), one_q(GATE_Z, 0)}});
    tests.push_back({"T05_HS_1Q", 1, "H then S: +pi/2 phase",
                     {one_q(GATE_H, 0), one_q(GATE_S, 0)}});
    tests.push_back({"T06_HT_1Q", 1, "H then T: +pi/4 phase",
                     {one_q(GATE_H, 0), one_q(GATE_T, 0)}});
    tests.push_back({"T07_RX_1Q", 1, "Rx(pi/3)",
                     {one_q(GATE_RX, 0, PI_F / 3.0f)}});
    tests.push_back({"T08_RY_1Q", 1, "Ry(0.7)",
                     {one_q(GATE_RY, 0, 0.7f)}});
    tests.push_back({"T09_HRZ_1Q", 1, "H then Rz(1.1)",
                     {one_q(GATE_H, 0), one_q(GATE_RZ, 0, 1.1f)}});

    tests.push_back({"T10_CNOT_2Q", 2, "Active CNOT",
                     {one_q(GATE_X, 1), two_q(GATE_CNOT, 1, 0)}});
    tests.push_back({"T11_CZ_2Q", 2, "CZ phase on |11>",
                     {one_q(GATE_X, 0), one_q(GATE_X, 1),
                      two_q(GATE_CZ, 0, 1)}});
    tests.push_back({"T12_BELL_2Q", 2, "Bell state",
                     {one_q(GATE_H, 0), two_q(GATE_CNOT, 0, 1)}});
    tests.push_back({"T13_GHZ_3Q", 3, "GHZ state",
                     {one_q(GATE_H, 0), two_q(GATE_CNOT, 0, 1),
                      two_q(GATE_CNOT, 1, 2)}});

    // SWAP is intentionally decomposed into three native CNOT operations.
    tests.push_back({"T14_SWAP_4Q", 4, "SWAP(q0,q3) = 3 CNOT",
                     {one_q(GATE_X, 0), two_q(GATE_CNOT, 0, 3),
                      two_q(GATE_CNOT, 3, 0), two_q(GATE_CNOT, 0, 3)}});

    tests.push_back({"T15_MIXED_5Q", 5, "Mixed native-gate circuit",
                     build_deep_mixed_circuit(5, 12)});
    tests.push_back({"T16_MIXED_6Q", 6, "Mixed native-gate circuit",
                     build_deep_mixed_circuit(6, 14)});
    tests.push_back({"T17_MIXED_7Q", 7, "Mixed native-gate circuit",
                     build_deep_mixed_circuit(7, 16)});
    tests.push_back({"T18_DEPTH20_8Q", 8,
                     "Deterministic mixed circuit with logical depth 20",
                     build_deep_mixed_circuit(8, 20)});

    return tests;
}

static bool run_test(
    const TestCase& tc,
    double& max_error,
    double& fidelity,
    double& norm_error) {

    static state_word_t state_vector[NUM_STATES];
    static instruction_word_t instructions[MAX_INSTRUCTIONS];

    const int active_states = 1 << tc.num_qubits;

    // Initial state |00...0>.
    for (int i = 0; i < active_states; ++i) {
        state_vector[i] = pack_state(q_real_t(0), q_real_t(0));
    }
    state_vector[0] = pack_state(q_real_t(1), q_real_t(0));

    // Clear instruction memory.
    for (int i = 0; i < MAX_INSTRUCTIONS; ++i) {
        instructions[i] = 0;
    }

    const int gate_count = static_cast<int>(tc.gates.size());

    if (gate_count > MAX_INSTRUCTIONS) {
        std::cerr
            << "Test " << tc.id
            << " has " << gate_count
            << " instructions, but MAX_INSTRUCTIONS="
            << MAX_INSTRUCTIONS << ".\n";
        return false;
    }

    for (int i = 0; i < gate_count; ++i) {
        instructions[i] = encode_host_gate(tc.gates[i]);
    }

    // FP32 golden reference for the exact same circuit.
    std::vector<RefComplex> reference(
        active_states,
        RefComplex(0.0f, 0.0f)
    );
    reference[0] = RefComplex(1.0f, 0.0f);

    for (int i = 0; i < gate_count; ++i) {
        apply_reference_gate(
            reference,
            tc.num_qubits,
            tc.gates[i]
        );
    }

    // DUT.
    quantum_simulator(
        state_vector,
        instructions,
        gate_count,
        tc.num_qubits
    );

    max_error = 0.0;

    double norm_hls = 0.0;
    double norm_ref = 0.0;
    std::complex<double> inner(0.0, 0.0);

    for (int i = 0; i < active_states; ++i) {
        const std::complex<double> hls(
            state_real(state_vector[i]).to_double(),
            state_imag(state_vector[i]).to_double()
        );

        const std::complex<double> ref(
            static_cast<double>(reference[i].real()),
            static_cast<double>(reference[i].imag())
        );

        max_error = std::max(
            max_error,
            std::abs(hls - ref)
        );

        norm_hls += std::norm(hls);
        norm_ref += std::norm(ref);
        inner += std::conj(ref) * hls;
    }

    norm_error = std::abs(norm_hls - 1.0);

    if (norm_hls > 0.0 && norm_ref > 0.0) {
        fidelity = std::norm(inner) / (norm_hls * norm_ref);
    } else {
        fidelity = 0.0;
    }

    // Clamp tiny numerical overshoot.
    if (fidelity > 1.0) {
        fidelity = 1.0;
    }

    return
        max_error <= EMAX_LIMIT &&
        fidelity >= FIDELITY_LIMIT &&
        norm_error <= NORM_ERROR_LIMIT;
}

int main() {
    const std::vector<TestCase> tests = build_tests();

    int passed = 0;

    std::cout
        << "HLS STANDARD C-SIM VALIDATION - 18 TESTS\n";

    std::cout
        << "Scope: 1..8 qubits, max "
        << MAX_INSTRUCTIONS
        << " instructions, HLS Q2.30 vs FP32 reference\n";

    std::cout
        << "Criteria: Emax <= " << EMAX_LIMIT
        << ", Fidelity >= " << FIDELITY_LIMIT
        << ", |norm-1| <= " << NORM_ERROR_LIMIT
        << "\n\n";

    std::cout
        << std::left << std::setw(20) << "TEST"
        << std::right << std::setw(4) << "Q"
        << std::setw(8) << "GATES"
        << std::setw(15) << "MAX_ERROR"
        << std::setw(15) << "FIDELITY"
        << std::setw(15) << "NORM_ERROR"
        << std::setw(10) << "RESULT"
        << "\n";

    std::cout << std::string(87, '-') << "\n";

    for (std::size_t i = 0; i < tests.size(); ++i) {
        double emax = 0.0;
        double fidelity = 0.0;
        double norm_error = 0.0;

        const bool ok = run_test(
            tests[i],
            emax,
            fidelity,
            norm_error
        );

        if (ok) {
            ++passed;
        }

        std::cout
            << std::left << std::setw(20) << tests[i].id
            << std::right << std::setw(4) << tests[i].num_qubits
            << std::setw(8) << tests[i].gates.size()
            << std::scientific << std::setprecision(3)
            << std::setw(15) << emax
            << std::fixed << std::setprecision(10)
            << std::setw(15) << fidelity
            << std::scientific << std::setprecision(3)
            << std::setw(15) << norm_error
            << std::setw(10) << (ok ? "PASS" : "FAIL")
            << "\n";
    }

    std::cout << std::string(87, '-') << "\n";
    std::cout
        << "PASS: " << passed
        << "/" << tests.size()
        << "\n";

    if (passed == static_cast<int>(tests.size())) {
        std::cout
            << "[PASS] HLS C-simulation meets the standardized "
               "18-test project accuracy criteria.\n";
        return 0;
    }

    std::cout
        << "[FAIL] At least one HLS validation case is outside "
           "the standardized project criteria.\n";
    return 1;
}
