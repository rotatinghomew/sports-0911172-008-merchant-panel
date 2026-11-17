from .store import require, money

class Distribution:
    def __init__(self,store):
        self.store=store

    def prepare(self,id,summary,recipients,reviewer):
        record=self.store.get('summary',summary)
        require(bool(reviewer) and bool(recipients),'分发授权为空')
        return self.store.put('release',id,dict(summary=summary,payload=record,
            recipients=recipients,reviewer=reviewer,state='prepared'),create=True)

    def send(self,id):
        with self.store.atomic():
            record=self.store.get('release',id)
            if record['state']=='sent':
                return record
            for source,revision in record['payload']['sources'].items():
                require(self.store.get('submission',source)['revision']==revision,'报送已更正，需重新准备')
            for recipient in record['recipients']:
                self.store.put('dispatch',f'{id}:{recipient}',dict(release=id,recipient=recipient),create=True)
            record['state']='sent'
            return self.store.put('release',id,record)
