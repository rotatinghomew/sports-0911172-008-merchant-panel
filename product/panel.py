from .store import require, money

class Panel:
    def __init__(self,store):
        self.store=store

    def register(self,id,sector,district,opened,closed=None):
        require(not closed or opened<closed,'营业区间无效')
        return self.store.put('merchant',id,dict(sector=sector,district=district,
            opened=opened,closed=closed,successors=[]),create=True)

    def merge(self,id,successors,effective):
        record=self.store.get('merchant',id)
        require(bool(successors) and id not in successors,'承接门店无效')
        for key in successors:
            self.store.get('merchant',key)
        record.update(closed=effective,successors=successors)
        return self.store.put('merchant',id,record)
