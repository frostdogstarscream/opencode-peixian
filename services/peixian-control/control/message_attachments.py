"""Account-owned filename snapshots; no document content or host paths."""
import json


def filename(value):
    if not isinstance(value,str):return '文件'
    value=value.replace('\\','/').rsplit('/',1)[-1]
    return ''.join(c for c in value if ord(c)>=32 and ord(c)!=127)[:255] or '文件'


def freeze(db,uid,ids,metadata):
    # Metadata comes from the authenticated Gateway text lookup, never the caller.
    selected={item['id']:item for item in metadata or [] if item.get('id') in ids}
    result=[]
    for fid in ids:
        item=selected.get(fid)
        if item is None:
            row=db.execute('SELECT metadata FROM files WHERE uid=? AND id=?',(uid,fid)).fetchone()
            item=json.loads(row['metadata']) if row else None
        if item is None:continue
        safe={'id':fid,'name':filename(item.get('name'))}
        result.append(safe)
        db.execute('INSERT OR IGNORE INTO files(uid,id,metadata) VALUES(?,?,?)',(uid,fid,json.dumps(safe,ensure_ascii=False)))
    return result


def project(store,uid,snapshot):
    if 'attachments' not in snapshot:
        # Legacy names were not frozen; do not parse prompts or invent filenames.
        return []
    result=[]
    allowed=set(snapshot.get('request',{}).get('file_ids',[]))
    for item in snapshot['attachments']:
        if item.get('id') not in allowed:continue
        exists=store.one('SELECT 1 AS found FROM files WHERE uid=? AND id=?',(uid,item['id']))
        result.append({'id':item['id'],'name':filename(item.get('name')),'status':'available' if exists else 'unavailable'})
    return result
