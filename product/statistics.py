from .store import require, money

class Statistics:
    def __init__(self,store):
        self.store=store

    def summarize(self,id,week,merchants):
        require(bool(merchants) and len(merchants)==len(set(merchants)),'研究对象无效')
        for key in merchants:
            self.store.get('merchant',key)
        reports=[item for item in self.store.all('submission') if item['week']==week and item['merchant'] in merchants]
        usable=[item for item in reports if item['status']=='reported']
        return self.store.put('summary',id,dict(week=week,merchants=merchants,
            reported=len(usable),missing=len(merchants)-len(usable),
            cents=sum(item['cents'] for item in usable),
            sources={item['id']:item['revision'] for item in reports}),create=True)
