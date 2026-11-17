from datetime import datetime, timezone


def flag_releases(store, kind, key):
    """报送更正或承接关系修订后，标识已发送且受影响的版本。

    已发出的内容保留原值，只追加更正标识；未发出的内容由发送前校验拦截。
    """
    source_field = 'submissions' if kind == 'submission' else 'merchants'
    for release in store.all('release'):
        if release['state'] not in ('sent', 'corrected'):
            continue
        sources = release.get('sources') or {}
        hit = key in sources.get(source_field, {})
        if not hit and kind == 'submission':
            hit = key in (release['payload'].get('sources') or {})
        if not hit:
            continue
        release.setdefault('corrections', []).append(
            {'kind': kind, 'source': key,
             'at': datetime.now(timezone.utc).isoformat()})
        release['state'] = 'corrected'
        store.put('release', release['id'], release)
