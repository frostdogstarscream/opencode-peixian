"""Release-owned identities; editable labels do not grant method authority."""
from .official_methods import BY_HASH
METHODS_BY_HASH = {key:value['method'] for key,value in BY_HASH.items() if value['method'] in ('night','companions','funds','relations') and value['state']=='published'}
