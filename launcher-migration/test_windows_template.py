"""Static safety checks for the NSIS candidate; not a native Windows acceptance."""

from pathlib import Path
import unittest


TEMPLATE = Path(__file__).with_name("windows-migration.nsi").read_text(encoding="utf-8")


class WindowsMigrationTemplateTests(unittest.TestCase):
    def test_only_fixed_existing_install_and_profile_can_migrate(self):
        for text in (
            'InstallDirRegKey HKCU "${REG}" "InstallDir"',
            'StrCpy $ProfileDir "$LOCALAPPDATA\\${APPNAME}"',
            'IfFileExists "$ProfileDir\\active.json" 0 preflight_failed',
            'IfFileExists "$INSTDIR\\resources\\app\\package.json" 0 preflight_failed',
            '${If} $INSTDIR != $ExpectedDir',
        ):
            self.assertIn(text, TEMPLATE)
        self.assertNotIn("MUI_PAGE_DIRECTORY", TEMPLATE)

    def test_candidate_checker_precedes_backup_and_checks_processes_twice(self):
        section = TEMPLATE.split('Section "启动器修复"', 1)[1]
        self.assertEqual(section.count("Call CheckMigration"), 2)
        self.assertLess(section.rindex("Call CheckMigration"), section.index('Rename "$INSTDIR" "$RollbackDir"'))
        self.assertIn('StrCpy $CheckRoot "$PLUGINSDIR\\payload"', TEMPLATE)
        self.assertIn('StrCpy $CheckRoot "$StageDir"', TEMPLATE)
        self.assertIn('"$CheckRoot\\resources\\app\\launcher-migration-check.mjs"', TEMPLATE)
        self.assertIn('w "ELECTRON_RUN_AS_NODE", w "1"', TEMPLATE)
        self.assertNotIn("taskkill", TEMPLATE.lower())
        self.assertNotIn("nsProcess", TEMPLATE)
        self.assertIn('--target windows-x64 --report-file "$CheckReport"', TEMPLATE)
        self.assertIn('--require-isolated', TEMPLATE)
        self.assertIn('w "ELECTRON_RUN_AS_NODE", p 0', TEMPLATE)
        self.assertIn('IfFileExists "$CheckReport" 0 checker_failed', TEMPLATE)

    def test_whole_old_directory_is_backed_up_and_failures_restore_it(self):
        self.assertIn('IfFileExists "$RollbackDir\\." preflight_failed', TEMPLATE)
        backup = TEMPLATE.index('Rename "$INSTDIR" "$RollbackDir"')
        activate = TEMPLATE.index('Rename "$StageDir" "$INSTDIR"')
        restore = TEMPLATE.index('Rename "$RollbackDir" "$INSTDIR"')
        self.assertLess(backup, activate)
        self.assertLess(activate, restore)
        self.assertNotIn("RMDir", TEMPLATE)
        self.assertNotIn("Delete ", TEMPLATE)
        self.assertNotIn("/REBOOTOK", TEMPLATE)

    def test_original_uninstaller_is_kept_without_replacing_registration(self):
        self.assertIn('CopyFiles /SILENT /FILESONLY "$INSTDIR\\Uninstall ${APPNAME}.exe" "$StageDir"', TEMPLATE)
        for command in ("WriteUninstaller", "UninstallString", "DeleteRegKey", 'Section "Uninstall"'):
            self.assertNotIn(command, TEMPLATE)

    def test_test_mode_cannot_write_production_entry_points(self):
        self.assertIn('ReadEnvStr $ProfileDir "OPEN_DEEPTUTOR_TEST_HOME"', TEMPLATE)
        self.assertIn('${If} $ProfileDir == "$LOCALAPPDATA\\${APPNAME}"', TEMPLATE)
        guarded = TEMPLATE.split("!ifndef TEST_MODE", 1)[1].split("!endif", 1)[0]
        for command in ("CreateShortcut", "WriteRegStr"):
            self.assertIn(command, guarded)
            self.assertEqual(TEMPLATE.count(command), guarded.count(command))
        self.assertNotIn("PARTS_MANIFEST", TEMPLATE)
        self.assertNotIn("ARCHIVE_NAME", TEMPLATE)


if __name__ == "__main__":
    unittest.main()
