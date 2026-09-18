from fastapi import Depends, Request
from .concurrency import blocking_endpoint
from .backend_contract import error, require_v6, iso
from .store import ident, now


def register(app):
    from .app import PREFIX, require_capability, body_fields
    read=require_capability('users.manage')
    write=require_capability('departments.manage')

    @app.get(PREFIX+'/admin/users/summary')
    @blocking_endpoint(app)
    def user_summary(request:Request,user=Depends(read)):
        s=app.state.store;require_v6(s)
        clause="role IN ('user','admin')" if user['role']=='super_admin' else "role='user'"
        rows=s.one('SELECT count(*) AS users,coalesce(sum(active),0) AS enabled FROM users WHERE '+clause)
        return {**rows,'disabled':rows['users']-rows['enabled'],'departments':s.one('SELECT count(*) AS n FROM departments')['n']}

    @app.get(PREFIX+'/admin/departments/tree')
    @blocking_endpoint(app)
    def departments_tree(request:Request,user=Depends(read)):
        s=app.state.store;require_v6(s);rows=s.rows('SELECT * FROM departments ORDER BY sort_order,name,id')
        nodes={x['id']:{**{k:v for k,v in x.items() if k!='updated'},'updated_at':iso(x['updated']),'children':[]} for x in rows}
        roots=[]
        for node in nodes.values():
            (nodes[node['parent_id']]['children'] if node['parent_id'] else roots).append(node)
        return {'items':roots,'total':len(rows),'page':1,'page_size':len(rows)}

    def fields(data):
        body_fields(data,('name','code','parent_id','sort_order'))
        for key in ('name','code'):
            if key in data and (not isinstance(data[key],str) or not 1<=len(data[key].strip())<=80 or any(ord(c)<32 for c in data[key])):error('invalid_department','部门名称或代码无效')
        if 'sort_order' in data and (type(data['sort_order']) is not int or not -10000<=data['sort_order']<=10000):error('invalid_sort_order','排序值无效')
        if 'parent_id' in data and data['parent_id'] is not None and not isinstance(data['parent_id'],str):error('invalid_parent','上级部门无效')
        return data

    def save(db,did,data):
        old=db.execute('SELECT * FROM departments WHERE id=?',(did,)).fetchone()
        values={**(dict(old) if old else {'parent_id':None,'sort_order':0}),**fields(data)}
        if not values.get('name') or not values.get('code'):error('department_fields_required','请填写部门名称和代码')
        parent=values['parent_id'];seen={did}
        while parent:
            if parent in seen:error('department_cycle','部门层级不能形成循环',409)
            seen.add(parent);row=db.execute('SELECT parent_id FROM departments WHERE id=?',(parent,)).fetchone()
            if not row:error('department_not_found','上级部门不存在',404)
            parent=row['parent_id']
        if db.execute('SELECT 1 FROM departments WHERE code=? AND id<>?',(values['code'],did)).fetchone():error('department_code_conflict','部门代码已存在',409)
        db.execute('INSERT INTO departments VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,code=excluded.code,parent_id=excluded.parent_id,sort_order=excluded.sort_order,updated=excluded.updated',(did,values['name'],values['code'],values['parent_id'],values['sort_order'],now()))
        return {'id':did,**{k:values[k] for k in ('name','code','parent_id','sort_order')}}

    @app.post(PREFIX+'/admin/departments',status_code=201)
    @blocking_endpoint(app,json_body=True)
    def department_create(request:Request,user=Depends(write)):
        s=app.state.store;require_v6(s)
        with s.tx() as db:return save(db,ident(),request.state.json_body)

    @app.patch(PREFIX+'/admin/departments/{did}')
    @blocking_endpoint(app,json_body=True)
    def department_edit(did:str,request:Request,user=Depends(write)):
        s=app.state.store;require_v6(s)
        with s.tx() as db:
            if not db.execute('SELECT 1 FROM departments WHERE id=?',(did,)).fetchone():error('department_not_found','部门不存在',404)
            return save(db,did,request.state.json_body)

    @app.delete(PREFIX+'/admin/departments/{did}')
    @blocking_endpoint(app)
    def department_delete(did:str,request:Request,user=Depends(write)):
        s=app.state.store;require_v6(s)
        with s.tx() as db:
            if not db.execute('SELECT 1 FROM departments WHERE id=?',(did,)).fetchone():error('department_not_found','部门不存在',404)
            if db.execute('SELECT 1 FROM departments WHERE parent_id=?',(did,)).fetchone() or db.execute('SELECT 1 FROM user_profiles WHERE department_id=?',(did,)).fetchone():error('department_not_empty','部门仍有下级或关联账号',409)
            db.execute('DELETE FROM departments WHERE id=?',(did,))
        return {'ok':True}
