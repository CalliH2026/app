"""Extract the official InstallScript launcher's embedded files; never run setup."""
import json,struct
from pathlib import Path

def extract(source,destination):
    data=source.read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0]
    if data[pe:pe+4]!=b'PE\0\0':raise ValueError('Not a PE installer')
    count=struct.unpack_from('<H',data,pe+6)[0];optional=struct.unpack_from('<H',data,pe+20)[0]
    table=pe+24+optional
    pos=max(struct.unpack_from('<I',data,table+i*40+20)[0]+struct.unpack_from('<I',data,table+i*40+16)[0] for i in range(count))
    files=struct.unpack_from('<I',data,pos)[0];pos+=4
    if not 1<=files<=100:raise ValueError('Unknown embedded file table')
    def string():
        nonlocal pos
        start=pos
        while data[pos:pos+2]!=b'\0\0':
            pos+=2
            if pos-start>10000:raise ValueError('Invalid installer metadata')
        value=data[start:pos].decode('utf-16-le');pos+=2;return value
    destination.mkdir(parents=True,exist_ok=True);manifest=[]
    for _ in range(files):
        name,target,version,size=string(),string(),string(),string()
        if '/' in name or '\\' in name or name in ('.','..'):raise ValueError('Unsafe file name')
        size=int(size)
        if size<0 or pos+size>len(data):raise ValueError('Invalid embedded payload length')
        (destination/name).write_bytes(data[pos:pos+size]);pos+=size
        manifest.append({'name':name,'target':target,'version':version,'bytes':size})
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest
if __name__=='__main__':
    import sys
    print(json.dumps(extract(Path(sys.argv[1]),Path(sys.argv[2])),ensure_ascii=False,indent=2))
