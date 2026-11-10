#ifndef QSIM_HLS_H
#define QSIM_HLS_H

#include <ap_fixed.h>
#include <ap_int.h>
#include <cstdint>

// -----------------------------------------------------------------------------
// Project scope / numerical policy
// -----------------------------------------------------------------------------
// Controlled comparison scope: 1..8 qubits on xc7z010clg400-1.
// Q2.30 fixed-point is used for the HLS candidate implementation.
// AP_RND_CONV reduces systematic truncation bias; AP_SAT prevents silent wrap
// on overflow. Accuracy is checked in the testbench against an independent
// FP32 golden model using Emax <= 1e-2 and fidelity >= 0.99.
typedef ap_fixed<32, 2, AP_RND_CONV, AP_SAT> q_real_t;

// Packed AXI state word: real[31:0], imag[63:32].
typedef ap_uint<64> state_word_t;

// 128-bit instruction word. The wider word keeps the interface simple while
// leaving room for gate type, target/control qubits and two fixed-point
// parameters (used as cos(theta/2), sin(theta/2) for rotation gates).
typedef ap_uint<128> instruction_word_t;

#define MAX_QUBITS 8
#define NUM_STATES (1 << MAX_QUBITS)

// The normalized experiment reserves up to 256 native instructions.
#define MAX_INSTRUCTIONS 256

#define INVALID_QUBIT 15

// Optional optimization switch. Keep 0 for the HLS baseline. After baseline
// C-simulation and synthesis are recorded, set to 1 and compare reports.
#ifndef QSIM_ENABLE_PIPELINE
#define QSIM_ENABLE_PIPELINE 0
#endif

enum GateType : uint8_t {
    GATE_I = 0,
    GATE_H = 1,
    GATE_X = 2,
    GATE_Y = 3,
    GATE_Z = 4,
    GATE_S = 5,
    GATE_T = 6,
    GATE_RX = 7,
    GATE_RY = 8,
    GATE_RZ = 9,
    GATE_CNOT = 10,
    GATE_CZ = 11
};

// -----------------------------------------------------------------------------
// Fixed-point pack / unpack helpers
// -----------------------------------------------------------------------------
static inline q_real_t unpack_fixed(ap_uint<32> raw) {
    q_real_t value;
    value.range(31, 0) = raw;
    return value;
}

static inline ap_uint<32> pack_fixed(q_real_t value) {
    ap_uint<32> raw = value.range(31, 0);
    return raw;
}

static inline state_word_t pack_state(q_real_t real, q_real_t imag) {
    state_word_t word = 0;
    word.range(31, 0) = pack_fixed(real);
    word.range(63, 32) = pack_fixed(imag);
    return word;
}

static inline q_real_t state_real(state_word_t word) {
    ap_uint<32> raw = word.range(31, 0);
    return unpack_fixed(raw);
}

static inline q_real_t state_imag(state_word_t word) {
    ap_uint<32> raw = word.range(63, 32);
    return unpack_fixed(raw);
}

// -----------------------------------------------------------------------------
// Instruction layout
// -----------------------------------------------------------------------------
// bits [3:0]   : gate opcode
// bits [7:4]   : target qubit  (0..7)
// bits [11:8]  : control qubit (0..7), INVALID_QUBIT for 1-qubit gates
// bits [43:12] : param0, Q2.30 raw bits
// bits [75:44] : param1, Q2.30 raw bits
// bits [127:76]: reserved
//
// For RX/RY/RZ:
//   param0 = cos(theta/2)
//   param1 = sin(theta/2)
// The host/testbench precomputes these values, avoiding sin/cos hardware in HLS.
static inline instruction_word_t encode_instruction(GateType gate,
                                                    uint8_t target,
                                                    uint8_t control = INVALID_QUBIT,
                                                    q_real_t param0 = q_real_t(0),
                                                    q_real_t param1 = q_real_t(0)) {
    instruction_word_t word = 0;
    word.range(3, 0) = static_cast<uint8_t>(gate);
    word.range(7, 4) = target;
    word.range(11, 8) = control;
    word.range(43, 12) = pack_fixed(param0);
    word.range(75, 44) = pack_fixed(param1);
    return word;
}

static inline GateType instruction_gate(instruction_word_t word) {
    return static_cast<GateType>(word.range(3, 0).to_uint());
}

static inline uint8_t instruction_target(instruction_word_t word) {
    return static_cast<uint8_t>(word.range(7, 4).to_uint());
}

static inline uint8_t instruction_control(instruction_word_t word) {
    return static_cast<uint8_t>(word.range(11, 8).to_uint());
}

static inline q_real_t instruction_param0(instruction_word_t word) {
    ap_uint<32> raw = word.range(43, 12);
    return unpack_fixed(raw);
}

static inline q_real_t instruction_param1(instruction_word_t word) {
    ap_uint<32> raw = word.range(75, 44);
    return unpack_fixed(raw);
}

// Top-level HLS accelerator.
// Only the first (1 << num_qubits) state entries are active.
void quantum_simulator(state_word_t state_vector[NUM_STATES],
                       instruction_word_t instructions[MAX_INSTRUCTIONS],
                       int num_inst,
                       int num_qubits);

#endif




