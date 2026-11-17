import argparse
import json
import sys
from pathlib import Path
from .store import Store
from .panel import Panel
from .submissions import Submissions
from .statistics import Statistics
from .growth import Growth
from .disclosure import Disclosure
from .distribution import Distribution


class Application:
    def __init__(self, path=':memory:'):
        self.store=Store(path)
        self.services={'panel':Panel(self.store),'submissions':Submissions(self.store),
            'statistics':Statistics(self.store),'growth':Growth(self.store),
            'disclosure':Disclosure(self.store),'distribution':Distribution(self.store)}

    def execute(self, command, arguments):
        service, separator, operation=command.partition('.')
        if not separator or operation.startswith('_') or service not in self.services:
            raise ValueError('未知业务操作')
        handler=getattr(self.services[service],operation,None)
        if not callable(handler):
            raise ValueError('未知业务操作')
        with self.store.atomic():
            return handler(**arguments)

    def replay(self, operations):
        return [self.execute(command,arguments) for command,arguments in operations]


def main():
    parser=argparse.ArgumentParser(description='体育商圈滚动商户样本的可比增长与披露控制本地操作台')
    parser.add_argument('action',choices=['demo','replay','inspect'])
    parser.add_argument('--db',default=':memory:')
    parser.add_argument('--file',type=Path)
    args=parser.parse_args()
    app=Application(args.db)
    try:
        if args.action=='demo':
            folder=Path(__file__).parent.parent/'data'
            results=app.replay(json.loads((folder/'demo.json').read_text()))
            results+=app.replay(json.loads((folder/'briefing.json').read_text()))
        elif args.action=='replay':
            if args.file is None:
                parser.error('replay 需要 --file')
            results=app.replay(json.loads(args.file.read_text()))
        else:
            results=[]
        print(json.dumps(dict(results=results,state=app.store.snapshot()),ensure_ascii=False,indent=2))
    except (ValueError,TypeError,KeyError) as error:
        print(str(error),file=sys.stderr)
        return 2
    finally:
        app.store.close()
    return 0
