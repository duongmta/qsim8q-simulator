#include "qsim_hls.h"

static const q_real_t INV_SQRT2 = q_real_t(0.70710678118654752440);

// Map pair number i to the basis-state index whose target bit is 0.
static inline int pair_index_zero(int i, int step) {
#pragma HLS INLINE
    return ((i & ~(step - 1)) << 1) | (i & (step - 1));
}

static void apply_single_qubit_gate(q_real_t local_real[NUM_STATES],
                                    q_real_t local_imag[NUM_STATES],
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
#pragma HLS PIPELINE II=1
#endif
        const int idx0 = pair_index_zero(i, step);
        const int idx1 = idx0 | step;

        const q_real_t ar = local_real[idx0];
        const q_real_t ai = local_imag[idx0];
        const q_real_t br = local_real[idx1];
        const q_real_t bi = local_imag[idx1];

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
            // diag(1, i)
            o1r = -bi;
            o1i = br;
            break;

        case GATE_T:
            // diag(1, exp(i*pi/4))
            o1r = INV_SQRT2 * (br - bi);
            o1i = INV_SQRT2 * (br + bi);
            break;

        case GATE_RX:
            // p0 = cos(theta/2), p1 = sin(theta/2)
            // [[c, -i s], [-i s, c]]
            o0r = p0 * ar + p1 * bi;
            o0i = p0 * ai - p1 * br;
            o1r = p1 * ai + p0 * br;
            o1i = -p1 * ar + p0 * bi;
            break;

        case GATE_RY:
            // [[c, -s], [s, c]]
            o0r = p0 * ar - p1 * br;
            o0i = p0 * ai - p1 * bi;
            o1r = p1 * ar + p0 * br;
            o1i = p1 * ai + p0 * bi;
            break;

        case GATE_RZ:
            // diag(exp(-i*theta/2), exp(i*theta/2))
            o0r = p0 * ar + p1 * ai;
            o0i = p0 * ai - p1 * ar;
            o1r = p0 * br - p1 * bi;
            o1i = p1 * br + p0 * bi;
            break;

        default:
            // Controlled gates are handled by apply_two_qubit_gate().
            break;
        }

        local_real[idx0] = o0r;
        local_imag[idx0] = o0i;
        local_real[idx1] = o1r;
        local_imag[idx1] = o1i;
    }
}

static void apply_two_qubit_gate(q_real_t local_real[NUM_STATES],
                                 q_real_t local_imag[NUM_STATES],
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
#pragma HLS PIPELINE II=1
#endif
        const int idx0 = pair_index_zero(i, step);

        // idx0 and idx1 differ only at target, so the control bit is identical
        // for both indices when control != target.
        if ((idx0 & control_mask) == 0) {
            continue;
        }

        const int idx1 = idx0 | step;

        if (gate == GATE_CNOT) {
            const q_real_t ar = local_real[idx0];
            const q_real_t ai = local_imag[idx0];
            local_real[idx0] = local_real[idx1];
            local_imag[idx0] = local_imag[idx1];
            local_real[idx1] = ar;
            local_imag[idx1] = ai;
        } else { // GATE_CZ
            local_real[idx1] = -local_real[idx1];
            local_imag[idx1] = -local_imag[idx1];
        }
    }
}

void quantum_simulator(state_word_t state_vector[NUM_STATES],
                       instruction_word_t instructions[MAX_INSTRUCTIONS],
                       int num_inst,
                       int num_qubits) {
#pragma HLS INTERFACE m_axi port=state_vector offset=slave bundle=gmem_state depth=NUM_STATES max_read_burst_length=16 max_write_burst_length=16
#pragma HLS INTERFACE m_axi port=instructions offset=slave bundle=gmem_inst depth=MAX_INSTRUCTIONS max_read_burst_length=16
#pragma HLS INTERFACE s_axilite port=state_vector bundle=ctrl
#pragma HLS INTERFACE s_axilite port=instructions bundle=ctrl
#pragma HLS INTERFACE s_axilite port=num_inst bundle=ctrl
#pragma HLS INTERFACE s_axilite port=num_qubits bundle=ctrl
#pragma HLS INTERFACE s_axilite port=return bundle=ctrl

    // Maximum-size local state keeps the interface fixed while num_qubits
    // controls how many entries are actually loaded, processed and stored.
    q_real_t local_real[NUM_STATES];
    q_real_t local_imag[NUM_STATES];

    // Baseline storage choice: true dual-port BRAM. No ARRAY_PARTITION or
    // BIND_OP is forced here; those are optimization experiments to be added
    // only after baseline synthesis results are recorded.
#pragma HLS BIND_STORAGE variable=local_real type=ram_t2p impl=bram
#pragma HLS BIND_STORAGE variable=local_imag type=ram_t2p impl=bram

    int nq = num_qubits;
    if (nq < 1) {
        nq = 1;
    } else if (nq > MAX_QUBITS) {
        nq = MAX_QUBITS;
    }
    const int active_states = 1 << nq;

load_state:
    for (int i = 0; i < active_states; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE II=1
#endif
        const state_word_t word = state_vector[i];
        local_real[i] = state_real(word);
        local_imag[i] = state_imag(word);
    }

    int instruction_count = num_inst;
    if (instruction_count < 0) {
        instruction_count = 0;
    } else if (instruction_count > MAX_INSTRUCTIONS) {
        instruction_count = MAX_INSTRUCTIONS;
    }

execute_inst:
    for (int i = 0; i < instruction_count; ++i) {
        const instruction_word_t word = instructions[i];
        const GateType gate = instruction_gate(word);
        const uint8_t target = instruction_target(word);
        const uint8_t control = instruction_control(word);

        // Ignore malformed/out-of-range instructions rather than accessing
        // state memory outside the active register.
        if (target >= nq) {
            continue;
        }

        if (gate == GATE_CNOT || gate == GATE_CZ) {
            if (control < nq && control != target) {
                apply_two_qubit_gate(local_real, local_imag, active_states,
                                     gate, control, target);
            }
        } else {
            apply_single_qubit_gate(local_real, local_imag, active_states,
                                    gate, target,
                                    instruction_param0(word),
                                    instruction_param1(word));
        }
    }

store_state:
    for (int i = 0; i < active_states; ++i) {
#if QSIM_ENABLE_PIPELINE
#pragma HLS PIPELINE II=1
#endif
        state_vector[i] = pack_state(local_real[i], local_imag[i]);
    }
}

