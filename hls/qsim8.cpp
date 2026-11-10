#include "qsim8.hpp"

// Return 0 on success, 1 on invalid dimensions/instruction. No state write on error.
int qsim8(state_word_t state_vector[NUM_STATES],
          instruction_word_t instructions[MAX_INSTRUCTIONS],
          int num_inst, int num_qubits);

static const q_real_t INV_SQRT2 = q_real_t(0.70710678118654752440);

// Map pair number i to the basis-state index whose target bit is 0.
static inline int pair_index_zero(int i, int step) {
#pragma HLS INLINE
    return ((i & ~(step - 1)) << 1) | (i & (step - 1));
}

// -----------------------------------------------------------------------------
// V6 single-qubit kernel: PACKED + IN-PLACE.
//
// Difference from V5:
//   V5: state_A -> kernel -> state_B  (two full state buffers, II=1, high BRAM)
//   V6: one packed 64-bit state RAM updated in place.
//
// Each iteration operates on one disjoint amplitude pair. Therefore there is no
// true inter-iteration dependency between different pair indices. The
// DEPENDENCE directive tells HLS not to serialize iterations because of a false
// memory dependency.
//
// A 1Q iteration needs 4 accesses to the state RAM:
//   read idx0, read idx1, write idx0, write idx1.
// With true dual-port BRAM (2 accesses/cycle), V6 intentionally targets II=2.
// -----------------------------------------------------------------------------
static void apply_single_qubit_gate(
    state_word_t state[NUM_STATES],
    int active_states,
    GateType gate,
    uint8_t target,
    q_real_t p0,
    q_real_t p1) {

#pragma HLS INLINE off

    if (gate == GATE_I || target >= MAX_QUBITS || active_states <= 1) {
        return;
    }

    const int step = 1 << target;
    const int pair_count = active_states >> 1;

single_gate_loop:
    for (int i = 0; i < pair_count; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE II=QSIM_V6_TARGET_II
#endif
        // For a fixed target, different loop iterations touch disjoint pairs.
#pragma HLS DEPENDENCE variable=state inter false

        const int idx0 = pair_index_zero(i, step);
        const int idx1 = idx0 | step;

        const state_word_t w0 = state[idx0];
        const state_word_t w1 = state[idx1];

        const q_real_t ar = state_real(w0);
        const q_real_t ai = state_imag(w0);
        const q_real_t br = state_real(w1);
        const q_real_t bi = state_imag(w1);

        q_real_t o0r = ar;
        q_real_t o0i = ai;
        q_real_t o1r = br;
        q_real_t o1i = bi;

        switch (gate) {
        case GATE_X:
            o0r = br;  o0i = bi;
            o1r = ar;  o1i = ai;
            break;

        case GATE_Y:
            // Y[a,b]^T = [-i*b, i*a]^T
            o0r = bi;   o0i = -br;
            o1r = -ai;  o1i = ar;
            break;

        case GATE_Z:
            o1r = -br;
            o1i = -bi;
            break;

        case GATE_H:
            o0r = INV_SQRT2 * (ar + br);
            o0i = INV_SQRT2 * (ai + bi);
            o1r = INV_SQRT2 * (ar - br);
            o1i = INV_SQRT2 * (ai - bi);
            break;

        case GATE_S:
            o1r = -bi;
            o1i = br;
            break;

        case GATE_T:
            o1r = INV_SQRT2 * (br - bi);
            o1i = INV_SQRT2 * (br + bi);
            break;

        case GATE_RX:
            o0r = p0 * ar + p1 * bi;
            o0i = p0 * ai - p1 * br;
            o1r = p1 * ai + p0 * br;
            o1i = -p1 * ar + p0 * bi;
            break;

        case GATE_RY:
            o0r = p0 * ar - p1 * br;
            o0i = p0 * ai - p1 * bi;
            o1r = p1 * ar + p0 * br;
            o1i = p1 * ai + p0 * bi;
            break;

        case GATE_RZ:
            o0r = p0 * ar + p1 * ai;
            o0i = p0 * ai - p1 * ar;
            o1r = p0 * br - p1 * bi;
            o1i = p1 * br + p0 * bi;
            break;

        default:
            break;
        }

        state[idx0] = pack_state(o0r, o0i);
        state[idx1] = pack_state(o1r, o1i);
    }
}

// -----------------------------------------------------------------------------
// V6 controlled 2-qubit kernel: PACKED + IN-PLACE.
//
// Pair indices are also disjoint across iterations. For inactive control pairs,
// no write is required because source and destination are the same memory.
// -----------------------------------------------------------------------------
static void apply_two_qubit_gate(
    state_word_t state[NUM_STATES],
    int active_states,
    GateType gate,
    uint8_t control,
    uint8_t target) {

#pragma HLS INLINE off

    if ((gate != GATE_CNOT && gate != GATE_CZ) ||
        control >= MAX_QUBITS || target >= MAX_QUBITS ||
        control == target || active_states <= 1) {
        return;
    }

    const int step = 1 << target;
    const int control_mask = 1 << control;
    const int pair_count = active_states >> 1;

controlled_gate_loop:
    for (int i = 0; i < pair_count; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE II=QSIM_V6_TARGET_II
#endif
#pragma HLS DEPENDENCE variable=state inter false

        const int idx0 = pair_index_zero(i, step);

        // Both members of a target pair have the same control bit because
        // control != target.
        if ((idx0 & control_mask) == 0) {
            continue;
        }

        const int idx1 = idx0 | step;

        if (gate == GATE_CNOT) {
            const state_word_t w0 = state[idx0];
            const state_word_t w1 = state[idx1];
            state[idx0] = w1;
            state[idx1] = w0;
        } else { // GATE_CZ
            const state_word_t w1 = state[idx1];
            state[idx1] = pack_state(-state_real(w1), -state_imag(w1));
        }
    }
}

int qsim8(state_word_t state_vector[NUM_STATES],
          instruction_word_t instructions[MAX_INSTRUCTIONS],
          int num_inst, int num_qubits) {
#pragma HLS INTERFACE m_axi port=state_vector offset=slave bundle=gmem_state depth=256 max_read_burst_length=16 max_write_burst_length=16 num_read_outstanding=2 num_write_outstanding=2
#pragma HLS INTERFACE m_axi port=instructions offset=slave bundle=gmem_inst depth=256 max_read_burst_length=16 num_read_outstanding=2
#pragma HLS INTERFACE s_axilite port=state_vector bundle=ctrl
#pragma HLS INTERFACE s_axilite port=instructions bundle=ctrl
#pragma HLS INTERFACE s_axilite port=num_inst bundle=ctrl
#pragma HLS INTERFACE s_axilite port=num_qubits bundle=ctrl
#pragma HLS INTERFACE s_axilite port=return bundle=ctrl
    state_word_t local_state[NUM_STATES];
    instruction_word_t local_inst[MAX_INSTRUCTIONS];
#pragma HLS BIND_STORAGE variable=local_state type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=local_inst type=ram_1p impl=bram
    if (num_qubits < 1 || num_qubits > MAX_QUBITS || num_inst < 0 || num_inst > MAX_INSTRUCTIONS)
        return 1;
    // Validate the entire program before modifying state. No silent clamping/skips.
validate_instructions:
    for (int k = 0; k < num_inst; ++k) {
        instruction_word_t w = instructions[k];
        unsigned op = w.range(3, 0).to_uint();
        unsigned target = instruction_target(w), control = instruction_control(w);
        if (op < GATE_H || op > GATE_CZ || target >= (unsigned)num_qubits || w.range(127, 76) != 0)
            return 1;
        if (op == GATE_CNOT || op == GATE_CZ) {
            if (control >= (unsigned)num_qubits || control == target) return 1;
        } else if (control != INVALID_QUBIT) return 1;
        if (op >= GATE_RX && op <= GATE_RZ) {
            q_real_t p0 = instruction_param0(w), p1 = instruction_param1(w);
            if (p0 < -1 || p0 > 1 || p1 < -1 || p1 > 1) return 1;
        } else if (w.range(75, 12) != 0) return 1;
        local_inst[k] = w;
    }
    const int count = 1 << num_qubits;
load_state:
    for (int i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
        local_state[i] = state_vector[i];
    }
execute_program:
    for (int k = 0; k < num_inst; ++k) {
        instruction_word_t w = local_inst[k];
        GateType gate = instruction_gate(w);
        if (gate == GATE_CNOT || gate == GATE_CZ)
            apply_two_qubit_gate(local_state, count, gate, instruction_control(w), instruction_target(w));
        else
            apply_single_qubit_gate(local_state, count, gate, instruction_target(w),
                                    instruction_param0(w), instruction_param1(w));
    }
store_state:
    for (int i = 0; i < count; ++i) {
#pragma HLS PIPELINE II=1
        state_vector[i] = local_state[i];
    }
    return 0;
}

