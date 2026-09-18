"""Public backend contract helpers; no upstream bodies enter management metadata."""
from datetime import datetime, timezone
import re
from fastapi import HTTPException

PROFILE_FIELDS = ("display_name", "police_no", "position", "department_id")
MODEL_FIELDS = ("provider", "context_length", "access_mode", "supports_tools")


def iso(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z') if value is not None else None


def error(code, message, status=422, fields=None):
    raise HTTPException(status, {"code":code,"message":message,"field_errors":fields or {}})


def require_v6(store):
    if store.schema_version()<6:error('backend_upgrade_required','此功能需要完成后端升级',503)


def page_values(page, page_size):
    if not 1<=page<=1000000 or not 1<=page_size<=100:error('invalid_pagination','分页参数无效')
    return (page-1)*page_size


def profile(db, uid):
    row=db.execute('SELECT p.*,d.name AS department_name,d.code FROM user_profiles p LEFT JOIN departments d ON d.id=p.department_id WHERE uid=?',(uid,)).fetchone()
    return {"display_name":row['display_name'] if row else '',"police_no":row['police_no'] if row else '',"position":row['position'] if row else '',"department_id":row['department_id'] if row else None,"department":{ "id":row['department_id'],"name":row['department_name'],"code":row['code']} if row and row['department_id'] else None,"last_login_at":iso(row['last_login']) if row else None}


def save_profile(db, uid, data, actor):
    values={k:data[k] for k in PROFILE_FIELDS if k in data}
    if not values:return
    if 'department_id' in values and actor['role']!='super_admin':error('department_forbidden','只有超级管理员可以修改部门归属',403)
    for key,value in values.items():
        if key=='department_id':
            if value is not None and (not isinstance(value,str) or not db.execute('SELECT 1 FROM departments WHERE id=?',(value,)).fetchone()):error('department_not_found','部门不存在',422,{key:'请选择有效部门'})
        elif not isinstance(value,str) or len(value)>80 or any(ord(c)<32 for c in value):error('invalid_profile','账号资料字段无效',422,{key:'使用不超过80字符的单行文字'})
    db.execute('INSERT OR IGNORE INTO user_profiles(uid) VALUES(?)',(uid,))
    for key,value in values.items():db.execute('UPDATE user_profiles SET '+key+'=? WHERE uid=?',(value,uid))


def model_profile(store, mid):
    if store.schema_version()<6:return {}
    row=store.one('SELECT * FROM model_profiles WHERE mid=?',(mid,))
    return {"provider":row['provider'] if row else 'openai-compatible',"context_length":row['context_length'] if row else None,"access_mode":row['access_mode'] if row else 'api',"supports_tools":bool(row['supports_tools']) if row else False,"test_status":row['test_status'] if row else 'untested',"updated_at":iso(row['updated']) if row else None}


def save_model_profile(db, mid, data, timestamp):
    if 'provider' in data and (not isinstance(data['provider'],str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,60}',data['provider'])):error('invalid_provider','模型提供方标识无效')
    if data.get('context_length') is not None and (type(data['context_length']) is not int or not 256<=data['context_length']<=2000000):error('invalid_context_length','上下文长度应为256至2000000')
    if 'access_mode' in data and data['access_mode'] not in ('api','local'):error('invalid_access_mode','接入方式仅支持api或local')
    if 'supports_tools' in data and type(data['supports_tools']) is not bool:error('invalid_supports_tools','工具支持必须是布尔值')
    db.execute('INSERT OR IGNORE INTO model_profiles(mid,updated) VALUES(?,?)',(mid,timestamp))
    for key in MODEL_FIELDS:
        if key in data:db.execute('UPDATE model_profiles SET '+key+'=? WHERE mid=?',(data[key],mid))
    db.execute("UPDATE model_profiles SET updated=?,test_status='untested' WHERE mid=?",(timestamp,mid))
