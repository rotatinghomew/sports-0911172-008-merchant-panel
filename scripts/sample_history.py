import random
import json
from datetime import date, timedelta

def generate():
    rng = random.Random(117208)
    operations = []

    def add(command, **arguments):
        operations.append([command, arguments])

    def day(offset):
        return (date(2026, 7, 1) + timedelta(days=offset)).isoformat()
    for index in range(30):
        add('panel.register', id=f'm{index}', sector=['food', 'sport', 'hotel'][index % 3], district=f'd{index % 4}', opened=day(index % 12))
    for week in range(12):
        for merchant in range(30):
            status = 'missing' if (week + merchant) % 11 == 0 else 'reported'
            add('submissions.report', id=f's{week}:{merchant}', merchant=f'm{merchant}', week=f'2026-W{27 + week}', cents=None if status == 'missing' else rng.randrange(0, 200000, 100), open_days=0 if status == 'missing' else 5 + merchant % 3, status=status)
        add('statistics.summarize', id=f'sum{week}', week=f'2026-W{27 + week}', merchants=[f'm{index}' for index in range(30)])
        if week % 3 == 0:
            add('distribution.prepare', id=f'rel{week}', summary=f'sum{week}', recipients=['alliance'], reviewer='finance')
            add('distribution.send', id=f'rel{week}')
    add('panel.merge', id='m0', successors=['m1', 'm2'], effective=day(82))
    add('submissions.correct', id='s11:2', cents=90000, reason='对账补正')
    return operations

def main():
    import argparse
    parser = argparse.ArgumentParser(description='生成本地合成业务记录，不包含真实个人资料')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    from pathlib import Path
    Path(args.output).write_text(json.dumps(generate(), ensure_ascii=False, indent=2) + '\n')

if __name__=='__main__':
    main()
