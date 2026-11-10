"""Manual regression, reference-only by default. --hardware explicitly uses UART."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .circuit import Circuit, compile_circuit, reference, compare, state_rows
from .transport import Board


def cases():
    # Cover every supported gate, every n in 1..8, phase and nonadjacent operands.
    return [
        ('H_1Q',1,0,[('H',0)]), ('X_1Q',1,0,[('X',0)]), ('Y_1Q',1,0,[('Y',0)]),
        ('HZ_1Q',1,0,[('H',0),('Z',0)]), ('HS_1Q',1,0,[('H',0),('S',0)]),
        ('HT_1Q',1,0,[('H',0),('T',0)]), ('RX_1Q',1,0,[('RX',0,0.7)]),
        ('RY_2Q',2,0,[('RY',1,-1.1)]), ('HRZ_3Q',3,0,[('H',2),('RZ',2,1.2)]),
        ('BELL_2Q',2,0,[('H',0),('CNOT',0,1)]),
        ('CZ_4Q',4,0,[('H',0),('H',3),('CZ',0,3)]),
        ('SWAP_5Q',5,1,[('SWAP',0,4)]),
        ('MIXED_6Q',6,0,[('H',5),('CNOT',5,0),('RY',3,0.43),('CZ',3,5)]),
        ('MIXED_7Q',7,0,[('H',6),('S',6),('CNOT',6,1),('SWAP',1,4),('RZ',4,0.73)]),
        ('GHZ_8Q',8,0,[('H',0)]+[('CNOT',q,q+1) for q in range(7)]),
    ]


def make_case(n,basis,ops):
    gates=[]
    for layer,op in enumerate(ops):
        name=op[0]
        if name in {'CNOT','CZ','SWAP'}:
            gates.append({'gate':name,'layer':layer,'control':op[1],'target':op[2]})
        else:
            g={'gate':name,'layer':layer,'target':op[1]}
            if name in {'RX','RY','RZ'}: g['theta']=op[2]
            gates.append(g)
    return Circuit(num_qubits=n,initial_basis=basis,gates=gates)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware',action='store_true',help='Connect and send all tests to the actual board')
    parser.add_argument('--port',default='COM14')
    args=parser.parse_args()
    board=Board(); results=[]
    try:
        if args.hardware: board.connect(args.port)
        for name,n,basis,ops in cases():
            c=make_case(n,basis,ops); code,summary=compile_circuit(c); expected=reference(c)
            row={'test':name,'circuit':c.model_dump(),'summary':summary,'reference':state_rows(expected,n)}
            if args.hardware:
                actual,timing,info=board.run(n,basis,code)
                row.update(state=state_rows(actual,n),timing=timing,board=info,metrics=compare(actual,expected))
                print(name, 'PASS' if row['metrics']['pass'] else 'FAIL')
            else:
                print(name,'REFERENCE_ONLY (no FPGA claim)')
            results.append(row)
    finally:
        board.disconnect()
        if results:
            folder=Path(__file__).resolve().parents[1]/'results'; folder.mkdir(exist_ok=True)
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            out=folder/f'{stamp}_{"hardware" if args.hardware else "reference"}.json'
            out.write_text(json.dumps({'mode':'hardware' if args.hardware else 'reference','tests':results},ensure_ascii=False,indent=2),encoding='utf-8')
            print('Saved:',out)
    if args.hardware:
        passed=sum(r['metrics']['pass'] for r in results)
        print(f'HARDWARE_ACCEPTANCE: {passed}/15')
        return 0 if passed==15 else 1
    print('Reference generation complete; FPGA acceptance has not been performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
