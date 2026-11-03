"""同じビルド環境のパッケージ表示を配布物へ収集する。"""
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys

def collect(destination):
    base=Path(destination)/'third-party/python-packages';base.mkdir(parents=True,exist_ok=True)
    result=[]
    for dist in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
        name=dist.metadata['Name'];folder=base/name;folder.mkdir(exist_ok=True)
        info={'name':name,'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License',''),'home':dist.metadata.get('Home-page','')}
        copied=[]
        for item in dist.files or []:
            text=str(item).replace('\\','/')
            if any(token in text.lower() for token in ('license','licence','copying','notice')) and '..' not in Path(text).parts:
                source=dist.locate_file(item)
                if source.is_file():
                    target=folder/text;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);copied.append(text)
        (folder/'metadata.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
        result.append({**info,'notices':copied})
    (base.parent/'python-packages.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    python=Path(sys.base_prefix)
    for source in (python/'LICENSE.txt',python/'LICENSE'):
        if source.exists():shutil.copy2(source,base.parent/'PYTHON-LICENSE.txt');break
if __name__=='__main__':collect(sys.argv[1])
