// User-run C simulation / C-RTL co-simulation.
// Independent double-complex reference: matrices and explicit basis-bit mapping.
#include "qsim8.hpp"
#include <complex>
#include <vector>
#include <cmath>
#include <iostream>
#include <algorithm>

using Complex = std::complex<double>;
struct Op { GateType gate; int target; int control; double theta; };
static unsigned cases = 0, failures = 0;
static Op op(GateType g, int t, int c = -1, double a = 0) { return {g,t,c,a}; }

static void reference_gate(std::vector<Complex>& s, const Op& g) {
    std::vector<Complex> out(s.size(), Complex(0,0));
    const unsigned mask = 1U << g.target;
    if (g.gate == GATE_CNOT || g.gate == GATE_CZ) {
        for (unsigned i = 0; i < s.size(); ++i) {
            bool ctrl = (i & (1U << g.control)) != 0;
            if (g.gate == GATE_CNOT) out[ctrl ? i ^ mask : i] = s[i];
            else out[i] = (ctrl && (i & mask)) ? -s[i] : s[i];
        }
    } else {
        Complex m[2][2] = {{1,0},{0,1}};
        const Complex j(0,1);
        const double r = 1 / std::sqrt(2.0), c = std::cos(g.theta/2), z = std::sin(g.theta/2);
        switch (g.gate) {
        case GATE_H: m[0][0]=r; m[0][1]=r; m[1][0]=r; m[1][1]=-r; break;
        case GATE_X: m[0][0]=0; m[0][1]=1; m[1][0]=1; m[1][1]=0; break;
        case GATE_Y: m[0][0]=0; m[0][1]=-j; m[1][0]=j; m[1][1]=0; break;
        case GATE_Z: m[1][1]=-1; break;
        case GATE_S: m[1][1]=j; break;
        case GATE_T: m[1][1]=std::exp(j * (std::acos(-1.0)/4)); break;
        case GATE_RX: m[0][0]=c; m[0][1]=-j*z; m[1][0]=-j*z; m[1][1]=c; break;
        case GATE_RY: m[0][0]=c; m[0][1]=-z; m[1][0]=z; m[1][1]=c; break;
        case GATE_RZ: m[0][0]=std::exp(-j*g.theta/2.0); m[1][1]=std::exp(j*g.theta/2.0); break;
        default: break;
        }
        for (unsigned i = 0; i < s.size(); ++i) {
            unsigned input_bit = (i & mask) ? 1 : 0;
            for (unsigned output_bit = 0; output_bit < 2; ++output_bit) {
                unsigned dest = (i & ~mask) | (output_bit ? mask : 0);
                out[dest] += m[output_bit][input_bit] * s[i];
            }
        }
    }
    s.swap(out);
}

static std::vector<Complex> complex_input(int n) {
    std::vector<Complex> s(1 << n);
    double norm = 0;
    for (unsigned i = 0; i < s.size(); ++i) {
        s[i] = Complex(std::sin(0.71*(i+1)), std::cos(0.39*(i+2)));
        norm += std::norm(s[i]);
    }
    for (auto& z : s) z /= std::sqrt(norm);
    return s;
}

static void run_case(const char* name, int n, std::vector<Complex> expected, const std::vector<Op>& ops) {
    state_word_t state[NUM_STATES];
    instruction_word_t instructions[MAX_INSTRUCTIONS];
    const state_word_t canary = pack_state(q_real_t(0.25), q_real_t(-0.25));
    for (int i = 0; i < NUM_STATES; ++i) state[i] = canary;
    for (int i = 0; i < MAX_INSTRUCTIONS; ++i) instructions[i] = 0;
    for (unsigned i = 0; i < expected.size(); ++i) {
        state[i] = pack_state(q_real_t(expected[i].real()), q_real_t(expected[i].imag()));
        expected[i] = Complex(state_real(state[i]).to_double(), state_imag(state[i]).to_double());
    }
    for (unsigned i = 0; i < ops.size(); ++i) {
        const Op& g = ops[i];
        bool rotation = g.gate >= GATE_RX && g.gate <= GATE_RZ;
        instructions[i] = encode_instruction(g.gate, g.target, g.control < 0 ? INVALID_QUBIT : g.control,
            rotation ? q_real_t(std::cos(g.theta/2)) : q_real_t(0),
            rotation ? q_real_t(std::sin(g.theta/2)) : q_real_t(0));
        reference_gate(expected, g);
    }
    int status = qsim8(state, instructions, (int)ops.size(), n);
    double error = 0, norm = 0;
    for (unsigned i = 0; i < expected.size(); ++i) {
        Complex got(state_real(state[i]).to_double(), state_imag(state[i]).to_double());
        error = std::max(error, std::abs(got - expected[i])); norm += std::norm(got);
    }
    bool pass = status == 0 && error < 1e-5 && std::abs(norm - 1) < 1e-5;
    for (int i = 1 << n; i < NUM_STATES; ++i) if (state[i] != canary) pass = false;
    ++cases; if (!pass) ++failures;
    std::cout << name << " n=" << n << " instructions=" << ops.size() << " max_error=" << error
              << " norm=" << norm << (pass ? " PASS" : " FAIL") << '\n';
}

int main() {
    for (int g = GATE_H; g <= GATE_RZ; ++g)
        run_case("individual_complex_gate", 1, complex_input(1), {op((GateType)g,0,-1,0.731)});
    for (int n = 2; n <= 8; ++n) {
        run_case("controlled_nonadjacent", n, complex_input(n),
                 {op(GATE_CNOT,n-1,0), op(GATE_CZ,0,n-1)});
    }
    for (int n = 1; n <= 8; ++n) {
        std::vector<Op> ops;
        // Exactly 20 logical layers, n disjoint single-qubit gates per layer.
        for (int layer = 0; layer < 20; ++layer)
            for (int q = 0; q < n; ++q)
                ops.push_back(op((GateType)(1+(layer+q)%9),q,-1,0.137*(layer+q+1)));
        run_case("depth20_all_targets", n, complex_input(n), ops);
    }
    std::vector<Complex> basis(256,0); basis[1] = 1;
    run_case("swap_q0_q7",8,basis,{op(GATE_CNOT,7,0),op(GATE_CNOT,0,7),op(GATE_CNOT,7,0)});
    std::vector<Op> swaps;
    for (int layer=0;layer<20;++layer) for(int q=0;q<8;q+=2) {
        swaps.push_back(op(GATE_CNOT,q+1,q)); swaps.push_back(op(GATE_CNOT,q,q+1)); swaps.push_back(op(GATE_CNOT,q+1,q));
    }
    run_case("240_native_instructions",8,complex_input(8),swaps);
    std::vector<Op> full(256,op(GATE_H,7));
    run_case("256_instruction_boundary",8,complex_input(8),full);
    run_case("empty_program",1,complex_input(1),{});

    state_word_t state[NUM_STATES] = {};
    instruction_word_t inst[MAX_INSTRUCTIONS] = {};
    state[0] = pack_state(q_real_t(1),q_real_t(0));
    inst[0] = encode_instruction(GATE_H,0);
    inst[1] = encode_instruction(GATE_H,8); // Invalid second instruction must not apply first H.
    bool rejected = qsim8(state,inst,2,8) != 0 && state[0] == pack_state(q_real_t(1),q_real_t(0));
    ++cases; if (!rejected) ++failures;
    bool bounds = qsim8(state,inst,257,8) != 0 && qsim8(state,inst,1,0) != 0 && qsim8(state,inst,1,9) != 0;
    ++cases; if (!bounds) ++failures;
    std::cout << "QSIM8_TEST=" << (failures ? "FAIL" : "PASS") << " cases=" << cases << " failures=" << failures << '\n';
    return failures ? 1 : 0;
}
