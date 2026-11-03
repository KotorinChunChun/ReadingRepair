"""配布ZIPの構成と既知のローカル秘密値の混入を検査する。値は出力しない。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

def verify(archive,report):
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'backend'))
    from reviewers import read_env
    secrets=[]
    for path in (Path('C:/AI/env/ReadingRepair/tts.env'),Path('C:/AI/env/ReadingRepair/reviewers.env')):
        for key,value in read_env(path).items():
            if any(token in key for token in ('PASSWORD','API_KEY','SECRET','TOKEN')) and len(value)>=8:secrets.append(value.encode())
    forbidden=[];found=[];total=0
    with zipfile.ZipFile(archive) as zipped:
        names=zipped.namelist()
        for info in zipped.infolist():
            name=info.filename;parts=Path(name).parts
            if not name.startswith('ReadingRepair/') or '..' in parts or any(part in ('runs','logs','.git','.venv','migration-original') for part in parts) or (name.endswith('.env') and not name.endswith('.env.example')) or any(part in ('app-job.json','original.txt','input.txt','user-answers.json','settings.json','user_dict_ja_jp.dic') for part in parts) or name.endswith('.wav'):forbidden.append(name)
            if info.is_dir():continue
            total+=info.file_size
            with zipped.open(info) as stream:
                tail=b'';overlap=max((len(value) for value in secrets),default=1)
                while True:
                    data=stream.read(1024*1024)
                    if not data:break
                    data=tail+data
                    if any(value in data for value in secrets):found.append(name);break
                    tail=data[-overlap:]
        required=('ReadingRepair/ReadingRepair.exe','ReadingRepair/backend/ReadingRepair.Backend.exe','ReadingRepair/registration/ReadingRepair.Registration.exe','ReadingRepair/backend/CodexClient.psm1','ReadingRepair/third-party/PYTHON-LICENSE.txt')
        missing=[name for name in required if name not in names]
    root=Path(__file__).resolve().parent.parent;source_found=[]
    for name in subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines():
        path=root/name
        if path.is_file() and any(value in path.read_bytes() for value in secrets):source_found.append(name)
    result={'archive':str(Path(archive).resolve()),'sha256':hashlib.sha256(Path(archive).read_bytes()).hexdigest(),'files':len(names),'uncompressed_bytes':total,'known_secret_values_checked':len(secrets),'forbidden_paths':forbidden,'missing':missing,'secret_files':found,'source_secret_files':source_found}
    result['passed']=not (forbidden or missing or found or source_found)
    Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(verify(sys.argv[1],sys.argv[2]))
