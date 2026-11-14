"""Native installed-core contract smoke. Synthetic records, no Key or network."""
import argparse
import asyncio
from contextlib import contextmanager, ExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import get_args
from unittest.mock import AsyncMock, patch


async def verify(root):
    from deeptutor.services import session, workspace
    from deeptutor.services.workspace import context
    from deeptutor.multi_user import learning_access
    from deeptutor.services.path_service import PathService
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore
    from deeptutor.services.student_learning import reports, report_textbooks
    from deeptutor.services.llm.exceptions import LLMAPIError

    subjects = get_args(reports.ReportSubject)
    stores = {key: SQLiteSessionStore(root / (key + '.db')) for key in subjects}
    active = ['']
    paths = PathService(workspace_root=root / 'account')
    paths.ensure_all_directories()

    @contextmanager
    def scope(key):
        previous, active[0] = active[0], key
        try:
            yield
        finally:
            active[0] = previous

    class Catalog:
        def describe_catalog(self):
            return {'root': str(root), 'workspaces': [
                {'workspace_id': key, 'display_name': key, 'path': str(root / ('student-study-' + key)),
                 'kind': 'workspace', 'status': 'ready', 'archived': False} for key in subjects]}

    results = []
    with ExitStack() as stack:
        for module, name, value in [
            (reports, 'get_account_path_service', lambda: paths),
            (reports, 'report_model_config', lambda _: None),
            (report_textbooks, 'report_textbook_scope', lambda _: []),
            (session, 'get_session_store', lambda: stores[active[0]]),
            (workspace, 'get_content_workspace_service', Catalog),
            (context, 'workspace_context', scope),
            (learning_access, 'learning_surface_allowed', lambda _: True),
        ]:
            stack.enter_context(patch.object(module, name, value))
        for subject, store in stores.items():
            for sid in ('lesson', 'reader'):
                await store.create_session(title='synthetic learning record', session_id=sid)
                mid = await store.add_message(sid, 'user', 'Synthetic ' + subject + ' learning evidence')
                with store._connect() as connection:
                    connection.execute('UPDATE messages SET created_at=? WHERE id=?',
                                       (datetime.fromisoformat('2024-02-28T02:00:00+00:00').timestamp(), mid))
            await store.update_session_preferences('reader', {'session_kind': 'immersive_reading'})
            before = {sid: await store.get_messages(sid) for sid in ('lesson', 'reader')}
            period = reports.ReportRange(from_date='2024-02-28', to_date='2024-02-28', subject=subject)

            row, task = await reports.begin(period)
            failed = AsyncMock(side_effect=LLMAPIError('synthetic provider failure'))
            await reports.generate(*task, complete=failed)
            shown = await reports.detail(row['id'])
            assert shown['state'] == 'failed' and 'subject_review' not in shown
            assert failed.await_count == 1

            row, task = await reports.begin(period)
            draft = await reports.bridge('records', {'source': task[3]})
            rejected = AsyncMock(side_effect=[json.dumps(draft), '{"approved":false,"issues":["synthetic mismatch"]}'])
            await reports.generate(*task, complete=rejected)
            assert (await reports.detail(row['id']))['state'] == 'failed'
            assert rejected.await_count == 2

            manager, notebook, saved = task[:3]
            reports.save(manager, notebook, {**saved, 'state': 'ready', 'stage': None,
                'result_level': 'records', 'policy': 'synthetic-old-policy', 'subject_review': draft})
            saved_before = manager.get_record(notebook, row['id'])
            assert (await reports.detail(row['id']))['state'] == 'failed'
            try:
                await reports.export_word(row['id'])
            except reports.ReportError:
                pass
            else:
                raise AssertionError('Unreviewed fallback exported as a final report')
            assert manager.get_record(notebook, row['id']) == saved_before

            row, task = await reports.begin(period)
            accepted = AsyncMock(side_effect=[json.dumps(draft), '{"approved":true,"issues":[]}'])
            await reports.generate(*task, complete=accepted)
            shown = await reports.detail(row['id'])
            assert shown['state'] == 'ready' and shown['result_level'] == 'full'
            assert accepted.await_count == 2
            assert (await reports.export_word(row['id'])).startswith(b'PK')
            assert {sid: await store.get_messages(sid) for sid in before} == before
            assert (await store.get_session('reader'))['preferences']['session_kind'] == 'immersive_reading'
            results.append({'subject': subject, 'generation_failure_rejected': True,
                'audit_failure_rejected': True, 'legacy_fallback_hidden_and_export_blocked': True,
                'reviewed_fixture_available_and_word_exported': True, 'chat_and_reading_records_preserved': True})
    return {'passed': True, 'native_platform': sys.platform, 'python': sys.version.split()[0],
            'cases': results, 'real_model_calls': 0, 'real_learner_data_used': False,
            'model_semantic_quality_tested': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--core-dir', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.core_dir.resolve(strict=True)))
    sys.dont_write_bytecode = True
    os.environ['PATH'] = str(args.node.resolve(strict=True).parent) + os.pathsep + os.environ.get('PATH', '')
    with tempfile.TemporaryDirectory(prefix='kaixin-report-smoke-') as temporary:
        os.environ['DEEPTUTOR_HOME'] = str(Path(temporary) / 'home')
        result = asyncio.run(verify(Path(temporary)))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
