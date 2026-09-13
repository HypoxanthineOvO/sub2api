"""Finite administrator workflow for the reviewed 235-237 upgrade only."""
from release_core import ReleaseError

SCHEMA_PHASES = {'schema_gate', 'schema_stopping', 'schema_backup', 'schema_migrating',
                 'schema_ready', 'schema_restoring', 'schema_opening', 'schema_reopening_old'}


class SchemaEngine:
    def __init__(self, host):
        self.host = host

    def stage(self, candidate, expected_old, database):
        h = self.host
        old = h.active()
        h.schema_preflight(old, candidate, expected_old, database)
        journal = {'phase': 'schema_gate', 'schema_maintenance': True, 'old': old, 'new': candidate,
                   'database': database, 'database_touched': False, 'traffic_opened': False}
        h.save_journal(journal)
        try:
            h.close_gate_and_drain()
            journal['phase'] = 'schema_stopping'; h.save_journal(journal)
            h.stop_schema_apps()
            journal['phase'] = 'schema_backup'; h.save_journal(journal)
            h.backup_schema_state(journal)
            journal.update(phase='schema_migrating', database_touched=True)
            h.save_journal(journal)
            h.prepare(candidate)
            h.healthy(candidate, direct=True)
            h.verify_migrated_database()
            h.assert_gate_closed()
            journal['phase'] = 'schema_ready'; h.save_journal(journal)
        except Exception:
            self.recover()
            raise

    def activate(self):
        h = self.host; journal = h.journal()
        if not journal or journal['phase'] != 'schema_ready':
            raise ReleaseError('schema upgrade is not awaiting administrator review')
        h.assert_gate_closed()
        h.healthy(journal['new'], direct=True)
        h.verify_migrated_database()
        # This boundary also precedes workers with external side effects.
        journal.update(phase='schema_opening', traffic_opened=True)
        h.save_journal(journal)
        self.finish_activation()

    def finish_activation(self):
        h = self.host; journal = h.journal()
        try:
            h.healthy(journal['new'], direct=True)
            h.commit_schema_baseline(journal['new'])
            h.transfer_workers(journal['new'])
            h.route(journal['new'])
            h.observe(journal['new'], [])
            journal['phase'] = 'complete'; h.save_journal(journal)
        except Exception:
            # Never discard possible customer writes after the opening boundary.
            try:
                h.close_gate_and_drain()
                h.pause_schema_workers()
            finally:
                journal['phase'] = 'recovery_failed'; h.save_journal(journal)
            raise ReleaseError('opening could not be verified; database retained, administrator action required')

    def abort(self):
        journal = self.host.journal()
        if not journal or journal.get('traffic_opened') or journal['phase'] != 'schema_ready':
            raise ReleaseError('automatic database restore is only allowed before opening traffic')
        self.recover(force=True)

    def recover(self, force=False):
        h = self.host; journal = h.journal()
        if not journal or journal['phase'] in {'complete', 'rolled_back', 'rejected', 'recovery_failed'}:
            return
        if journal.get('traffic_opened'):
            self.finish_activation()
            return
        if journal.get('database_restored'):
            self.finish_restoration()
            return
        if journal['phase'] == 'schema_ready' and not force:
            return  # Successful staging intentionally waits behind the maintenance gate.
        try:
            if journal.get('database_touched'):
                h.close_gate_and_drain()
                h.stop_schema_apps()
                journal['phase'] = 'schema_restoring'; h.save_journal(journal)
                h.restore_schema_state(journal)
            # Before starting old workers or restoring ingress, commit the fact
            # that a second DB restore is no longer allowed after a crash.
            journal.update(phase='schema_reopening_old', database_restored=True)
            h.save_journal(journal)
            self.finish_restoration()
        except Exception:
            current = h.journal()
            current['phase'] = 'recovery_failed'; h.save_journal(current)
            raise ReleaseError('schema recovery could not be verified; keep maintenance closed')

    def finish_restoration(self):
        h = self.host; journal = h.journal()
        try:
            h.restore_schema_app(journal['old'])
            h.route(journal['old'])
            h.healthy(journal['old'], direct=False)
            h.restore_committed(journal['old'])
            journal['phase'] = 'rolled_back'; h.save_journal(journal)
        except Exception:
            try: h.close_gate_and_drain()
            finally:
                journal['phase'] = 'recovery_failed'; h.save_journal(journal)
            raise ReleaseError('old application recovery needs administrator review; do not replay the database restore')
