"""明示的に許可されたVoiSona辞書だけを、独立したローカルGitへ同期する。"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


FORMAT = 'readingrepair.dictionary-git.v1'


def sync(config_file, settings):
    if settings.get('tts_engine', 'voisona') != 'voisona':
        return {'status': 'disabled', 'reason': 'other_engine'}
    if not Path(config_file).is_file():
        return {'status': 'disabled', 'reason': 'not_configured'}
    try:
        config = json.loads(Path(config_file).read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict) or set(config) != {'format', 'enabled', 'repository', 'source_dictionary'}:
            raise ValueError('辞書Git連携の設定項目が一致しません。')
        if config['format'] != FORMAT or type(config['enabled']) is not bool:
            raise ValueError('辞書Git連携の設定形式が不正です。')
        if not config['enabled']:
            return {'status': 'disabled', 'reason': 'disabled_by_settings'}
        for key in ('repository', 'source_dictionary'):
            if not isinstance(config[key], str) or not config[key].strip() or '\x00' in config[key]:
                raise ValueError('辞書Git連携のパスが不正です。')
        source = Path(settings['dictionary_file']).resolve()
        if os.path.normcase(str(source)) != os.path.normcase(str(Path(config['source_dictionary']).resolve())):
            return {'status': 'skipped', 'reason': 'different_dictionary',
                    'message': '許可した実辞書と異なるためGit同期を省略しました。'}
        repo = Path(config['repository']).resolve()
        script = repo / 'scripts/Sync-Dictionary.ps1'
        if not (repo / '.git').exists() or not script.is_file():
            raise ValueError('辞書の独立Gitリポジトリまたは同期CLIがありません。')
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(('VOISONA_', 'GEMINI_', 'SARASHINA_', 'GOOGLE_', 'READINGREPAIR_', 'TTS_'))}
        completed = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(script),
                                    '-SourceFile', str(source), '-Commit',
                                    '-Message', 'ReadingRepairの辞書更新を自動同期する'],
                                   capture_output=True, encoding='utf-8', errors='replace',
                                   timeout=60, env=environment)
        if completed.returncode:
            detail = re.sub(r'\x1b\[[0-9;]*m', '', completed.stderr).strip()[-1200:]
            return {'status': 'failed', 'repository': str(repo), 'error_type': 'SyncCommandFailed',
                    'message': '辞書Git同期CLIが失敗しました。', 'detail': detail}
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        result = json.loads(lines[-1])
        if (not isinstance(result, dict) or type(result.get('committed')) is not bool
                or type(result.get('changed')) is not bool or type(result.get('entry_count')) is not int
                or result['entry_count'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', str(result.get('sha256', '')))
                or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', str(result.get('commit', '')))):
            raise ValueError('辞書Git同期CLIの結果を確認できません。')
        if result['sha256'] != hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError('同期中に実辞書が変わりました。最新の辞書で再同期してください。')
        return {**result, 'status': 'committed' if result['committed'] else 'unchanged',
                'repository': str(repo), 'message': '辞書の変更をコミットしました。' if result['committed'] else '辞書の変更なし。空コミットは作成しません。'}
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else '辞書Git同期に失敗しました。辞書と登録済み内容は保持します。'
        return {'status': 'failed', 'error_type': type(error).__name__, 'message': message}
