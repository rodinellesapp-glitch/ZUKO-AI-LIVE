"""Public display names only; never use internal IDs or interpret instructions."""
import re
import unicodedata

def public_name(value):
    if not isinstance(value,str):return ''
    value=unicodedata.normalize('NFC',value).strip().lstrip('@')
    if not value or len(value)>48 or not any(c.isalpha() for c in value):return ''
    if any(unicodedata.category(c) in {'Cc','Cf'} for c in value):return ''
    folded=''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if not unicodedata.combining(c))
    if re.search(r'https?://|www\.|[{}<>\[\]\\]|\b(ignore|execute|system|prompt|powershell|senha|token|puta|puto|idiota|imbecil|caralho|porra)\b',folded):return ''
    return value
