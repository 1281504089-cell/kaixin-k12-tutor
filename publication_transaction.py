"""One bounded publication attempt, with readback after every uncertain write."""
import hashlib
import json


class PublicationIncomplete(RuntimeError):
    pass


def publish_transaction(backend, *, tag, commit, pointers, previous, installation,
                        receipt_file, receipt_factory, journal_file, title, notes,
                        expected_latest_id, check_immutable=lambda: True):
    digest = lambda raw: hashlib.sha256(raw).hexdigest() if raw is not None else None
    candidate = backend.release(tag)
    old_latest = backend.latest()
    assert old_latest['id'] == expected_latest_id, 'Latest changed before transaction'
    assert candidate['prerelease'] is True and candidate['draft'] is False, 'Candidate is no longer a public prerelease'
    old_tag = backend.tag_sha(tag)
    old_fields = {k: candidate[k] for k in ('name', 'body', 'prerelease', 'draft')}
    new_fields = dict(name=title, body=notes, prerelease=False, draft=False)
    old_assets = {name: backend.asset_bytes(tag, name)
                  for name in ('INSTALLATION.txt', 'PUBLICATION-RECEIPT.json')}
    changes = []
    journal = dict(status='started', tag=tag, commit=commit,
                   old_tag_sha=old_tag, old_latest_id=old_latest['id'],
                   attempted=[], observations=[], recovery=[])

    def save():
        journal_file.write_text(json.dumps(journal, ensure_ascii=False, indent=2) + '\n')

    def observe(label, check):
        try:
            result = check()
            journal['observations'].append(dict(phase=label, matched=bool(result)))
            save()
            return result
        except Exception as error:
            journal['observations'].append(dict(phase=label, error=str(error)))
            save()
            raise

    def attempt(label, write, matches, restore, old_matches):
        # Register before invoking gh: delete/upload may succeed before its response is lost.
        changes.append((label, restore, old_matches))
        journal['attempted'].append(label)
        save()
        error = None
        try:
            write()
        except Exception as caught:
            error = caught
            journal['observations'].append(dict(phase=label, write_error=str(caught)))
        if not observe(label, matches):
            raise PublicationIncomplete('Write was not confirmed: ' + label) from error

    def asset_change(release_tag, name, raw, old):
        def current():
            return backend.asset_bytes(release_tag, name)

        def restore():
            actual = current()
            if actual == old:
                return
            if actual is not None and actual != raw:
                raise PublicationIncomplete('Concurrent asset change: ' + name)
            if old is None:
                backend.delete_asset(release_tag, name)
            else:
                backend.upload_bytes(release_tag, name, old)

        journal.setdefault('asset_sha256', {})[release_tag + '/' + name] = dict(old=digest(old), new=digest(raw))
        attempt('asset:' + release_tag + '/' + name,
                lambda: backend.upload_bytes(release_tag, name, raw),
                lambda: current() == raw, restore, lambda: current() == old)

    def current_fields():
        current = backend.release(tag)
        return {k: current[k] for k in old_fields}

    def restore_tag():
        actual = backend.tag_sha(tag)
        if actual == old_tag:
            return
        if actual != commit:
            raise PublicationIncomplete('Concurrent tag change')
        backend.set_tag(tag, old_tag)

    def old_release_matches():
        return current_fields() == old_fields and backend.latest()['id'] == old_latest['id']

    def restore_release():
        actual_fields = current_fields()
        latest_id = backend.latest()['id']
        if actual_fields not in (old_fields, new_fields) or latest_id not in (old_latest['id'], candidate['id']):
            raise PublicationIncomplete('Concurrent Latest/release change')
        if actual_fields != old_fields:
            try:
                backend.edit_release(candidate['id'], old_fields, latest=False)
            except Exception:
                if current_fields() != old_fields:
                    raise
        if backend.latest()['id'] != old_latest['id']:
            backend.edit_release(old_latest['id'], {k: old_latest[k] for k in old_fields}, latest=True)

    def target_complete():
        return (check_immutable()
                and all(backend.asset_bytes('core-updates', name) == raw for name, raw in pointers.items())
                and backend.asset_bytes(tag, 'INSTALLATION.txt') == installation
                and backend.tag_sha(tag) == commit and current_fields() == new_fields
                and backend.latest()['id'] == candidate['id'])

    save()
    try:
        assert check_immutable()
        for name, raw in pointers.items():
            assert backend.asset_bytes('core-updates', name) == previous[name], 'Feed changed before write: ' + name
            asset_change('core-updates', name, raw, previous[name])
        asset_change(tag, 'INSTALLATION.txt', installation, old_assets['INSTALLATION.txt'])
        assert backend.tag_sha(tag) == old_tag, 'Tag changed before write'
        attempt('tag', lambda: backend.set_tag(tag, commit), lambda: backend.tag_sha(tag) == commit,
                restore_tag, lambda: backend.tag_sha(tag) == old_tag)
        assert old_release_matches(), 'Latest/release changed before write'
        attempt('latest', lambda: backend.edit_release(candidate['id'], new_fields, latest=True),
                lambda: current_fields() == new_fields and backend.latest()['id'] == candidate['id'],
                restore_release, old_release_matches)
        assert target_complete()
        receipt = receipt_factory(backend.latest())
        receipt_raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode()
        receipt_file.write_bytes(receipt_raw)
        asset_change(tag, 'PUBLICATION-RECEIPT.json', receipt_raw, old_assets['PUBLICATION-RECEIPT.json'])
        journal['status'] = 'published_and_receipt_verified'
        save()
        return receipt
    except Exception as error:
        journal['error'] = str(error)
        try:
            complete = target_complete()
        except Exception as read_error:
            complete = False
            journal['target_readback_error'] = str(read_error)
        if complete:
            # Do not re-publish or undo an already consistent public release to repair a receipt.
            journal['status'] = 'published_but_receipt_incomplete'
            save()
            raise PublicationIncomplete('Published state is complete; repair only the receipt after reading this journal') from error
        for label, restore, old_matches in reversed(changes):
            row = dict(phase=label)
            journal['recovery'].append(row)
            try:
                if not old_matches():
                    try:
                        restore()
                    except Exception as restore_error:
                        row['write_error'] = str(restore_error)
                    row['restored_and_read_back'] = bool(old_matches())
                else:
                    row['restored_and_read_back'] = True
            except Exception as recovery_error:
                row['error'] = str(recovery_error)
                row['restored_and_read_back'] = False
            save()
        journal['status'] = ('failed_and_previous_state_verified' if all(r['restored_and_read_back'] for r in journal['recovery'])
                             else 'failed_recovery_requires_owner_readback')
        save()
        raise PublicationIncomplete(journal['status'] + '; no automatic retry') from error
