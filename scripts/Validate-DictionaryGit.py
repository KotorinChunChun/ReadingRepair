"""TTS更新を隔離データで模擬し、終了後の同期・コミットを実pwshと実Gitで検証する。"""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from application import Application
import lab


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync-script', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    steps = []

    def command(parts):
        result = subprocess.run([str(p) for p in parts], check=True, capture_output=True, encoding='utf-8', errors='replace')
        return result.stdout.strip()

    def fixture(name):
        root = output / name; repo = root / 'repo'; (repo / 'scripts').mkdir(parents=True)
        shutil.copyfile(args.sync_script, repo / 'scripts/Sync-Dictionary.ps1')
        (repo / '.gitattributes').write_text('*.dic -text\n', encoding='utf-8')
        source = root / 'native.dic'; source.write_text('既存 [キソン] ACCENT="0"\n', encoding='utf-8')
        def git(*parts): return command(['git', '-C', repo, *parts])
        git('init', '-q', '-b', 'main')
        git('config', 'user.name', '辞書自動同期試験')
        git('config', 'user.email', 'test@example.invalid')
        git('config', 'commit.gpgsign', 'false')
        command(['pwsh', '-NoProfile', '-File', repo/'scripts/Sync-Dictionary.ps1', '-SourceFile', source, '-Commit'])
        app = Application(root, root / 'settings.json')
        app.save_settings({'runs_root':str(root/'runs'), 'dictionary_file':str(source), 'api_dictionary_file':str(root/'api.json')})
        lab.save(root/'dictionary-git.json', {'format':'readingrepair.dictionary-git.v1','enabled':True,
                                             'repository':str(repo),'source_dictionary':str(source)})
        return root, repo, source, app, git

    def check(value, message):
        if not value: raise AssertionError(message)
        steps.append(message)

    root, repo, source, app, git = fixture('batch')
    def register(run_dir, dictionary_file, text, entries):
        with source.open('a', encoding='utf-8') as stream:
            for entry in entries: stream.write(entry['surface']+' ['+entry['reading']+'] ACCENT="0"\n')
        return {'entries':entries,'method':'isolated-registration-fixture'}
    request={'entries':[{'surface':'追加甲','reading':'ツイカコウ'},{'surface':'追加乙','reading':'ツイカオツ'}]}
    checked=app.check_dictionary(request)
    with patch('application.lab.register_entries', side_effect=register), redirect_stdout(io.StringIO()):
        result=app.add_dictionary({**request,'dictionary_sha256':checked['dictionary_sha256']})
    check(result['dictionary_git_sync']['status']=='committed' and git('rev-list','--count','HEAD')=='2'
          and result['dictionary_git_sync']['commit']==git('rev-parse','HEAD')
          and set(git('diff','--name-only','HEAD~1','HEAD').splitlines())=={'dictionary/user_dict_ja_jp.dic','dictionary/manifest.json'},
          '一括2語の登録後に実Gitへ1コミットだけ追加し、IDと追跡対象を確認')
    head=git('rev-parse','HEAD')
    checked=app.check_dictionary(request)
    with redirect_stdout(io.StringIO()):
        result=app.add_dictionary({**request,'dictionary_sha256':checked['dictionary_sha256']})
    check(result['dictionary_git_sync']['status']=='unchanged' and git('rev-parse','HEAD')==head,
          '変更なしの終了処理は実Gitに空コミットを作らない')

    for outcome in ('pending_confirmation','cancelled','failed'):
        root, repo, source, app, git = fixture(outcome)
        job=app.create({'text':'検証'})
        def run(stage_args):
            with source.open('a',encoding='utf-8') as stream:stream.write('途中登録 [トチュートーロク] ACCENT="0"\n')
            lab.save(stage_args.run_dir/'manifest.json',{'status':outcome})
            if outcome=='cancelled':raise InterruptedError('停止の模擬')
            if outcome=='failed':raise RuntimeError('部分登録後の失敗の模擬')
        with patch('application.lab.run',side_effect=run),patch('application.lab.export_current_history'),redirect_stdout(io.StringIO()):
            result=app.execute(job['id'])
        check(result['status']==outcome and result['dictionary_git_sync']['status']=='committed'
              and git('rev-list','--count','HEAD')=='2',outcome+'でも登録済み変更を実Gitへ自動コミット')

    root, repo, source, app, git = fixture('retry')
    (repo/'unrelated.md').write_text('別の作業',encoding='utf-8');git('add','--','unrelated.md')
    job=app.create({'text':'検証'})
    def run(stage_args):
        with source.open('a',encoding='utf-8') as stream:stream.write('追加 [ツイカ] ACCENT="0"\n')
        lab.save(stage_args.run_dir/'manifest.json',{'status':'completed'})
    with patch('application.lab.run',side_effect=run),patch('application.lab.export_current_history'),redirect_stdout(io.StringIO()):
        result=app.execute(job['id'])
    check(result['status']=='completed' and result['dictionary_git_sync']['status']=='failed'
          and git('rev-list','--count','HEAD')=='1' and git('diff','--cached','--name-only')=='unrelated.md',
          '他作業のステージ内容がある場合は混在コミットせず、元の処理結果と辞書を保持')
    git('restore','--staged','--','unrelated.md')
    with patch('application.lab.run') as run_again,patch('application.lab.export_current_history'),redirect_stdout(io.StringIO()):
        result=app.execute(job['id'])
    run_again.assert_not_called()
    check(result['dictionary_git_sync']['status']=='committed' and git('rev-list','--count','HEAD')=='2',
          '完了済み実行の再同期はTTSを再実行せず残りのGitコミットを実行')

    app.save_settings({'tts_engine':'http-wav'})
    head=git('rev-parse','HEAD')
    check(app.sync_dictionary_git()['status']=='disabled' and git('rev-parse','HEAD')==head,
          'HTTP TTSはVoiSona辞書リポジトリの同期対象にしない')
    lab.save(output/'result.json',{'passed':True,'tests':len(steps),'steps':steps,
                                 'registration':'isolated fixture','git':'real local Git','tts_or_external_llm_called':False})
    print(json.dumps({'passed':True,'tests':len(steps),'output':str(output)},ensure_ascii=False))


if __name__=='__main__':main()
