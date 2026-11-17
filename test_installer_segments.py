import unittest
from ci_repackage import validate_installer_files

class SegmentTests(unittest.TestCase):
    def files(self,target,count):
        brand='Intel' if target=='macos-x64' else 'Apple-Silicon'
        stem='Kaixin-Super-Scholar-MacOS-'+brand+'-v1.7.1-20261117-k12-5-part'
        return [{'file':stem+('.dmg' if i==1 else f'.{i:03d}.dmgpart'),'bytes':100} for i in range(1,count+1)]
    def test_all_contiguous_mac_parts_including_growth_to_five(self):
        for target in ['macos-x64','macos-arm64']:
            for count in [4,5]:
                validate_installer_files(self.files(target,count),target,'student-20261117-k12-5')
    def test_missing_duplicate_or_oversize_segment_rejected(self):
        files=self.files('macos-x64',5)
        for changed in [files[:1]+files[2:],files+[files[-1]],files[:-1]+[{**files[-1],'bytes':2_000_000_000}]]:
            with self.assertRaises(AssertionError):validate_installer_files(changed,'macos-x64','student-20261117-k12-5')
    def test_windows_still_requires_exact_setup_and_four_runtime_parts(self):
        stem='Kaixin-Super-Scholar-Windows-v1.7.1-'
        files=[{'file':stem+name,'bytes':100} for name in ['Setup.exe','Runtime.001','Runtime.002','Runtime.003','Runtime.004']]
        validate_installer_files(files,'windows-x64','student-20261117-k12-5')
        with self.assertRaises(AssertionError):validate_installer_files(files[:-1],'windows-x64','student-20261117-k12-5')

if __name__=='__main__':unittest.main()
