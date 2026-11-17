from .store import require, money

class Submissions:
    def __init__(self,store):
        self.store=store

    def report(self,id,merchant,week,cents,open_days,status='reported'):
        self.store.get('merchant',merchant)
        require(status in ('reported','missing','closed'),'报送状态无效')
        require(0<=open_days<=7,'营业天数无效')
        require((status=='reported' and cents is not None) or (status!='reported' and cents is None),'缺报不得填销售额')
        if cents is not None:
            money(cents)
        require(not any(item['merchant']==merchant and item['week']==week for item in self.store.all('submission')),'本期已报送')
        return self.store.put('submission',id,dict(merchant=merchant,week=week,cents=cents,
            open_days=open_days,status=status),create=True)

    def correct(self,id,cents,reason):
        record=self.store.get('submission',id)
        require(bool(reason),'更正说明为空')
        record.update(cents=money(cents),status='reported',reason=reason)
        return self.store.put('submission',id,record)
