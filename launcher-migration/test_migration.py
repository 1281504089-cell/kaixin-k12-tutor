#!/usr/bin/env python3
"""Small offline self-check: synthetic keys/profiles only, no installer execution or network."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import unittest

import package_launcher as package
import verify_profile

PARSER = argparse.ArgumentParser()
PARSER.add_argument("--node", required=True)
PARSER.add_argument("--frozen-source", required=True)
ARGS, REST = PARSER.parse_known_args()
SOURCE = Path(ARGS.frozen_source) / "apps/desktop"
NODE = ARGS.node
HERE = Path(__file__).resolve().parent


def node(code, **env):
    return package.run([NODE, "--input-type=module", "-e", code], env={**os.environ, **env})


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="selfcheck-", dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, target="macos-x64", active_base="77f2ba387"):
        app = self.root / ("final.app" if target.startswith("macos-") else "final")
        shell = package.resources(app, target) / "app"
        shell.mkdir(parents=True)
        for folder in ("src", "assets"):
            shutil.copytree(SOURCE / folder, shell / folder)
        (shell / "package.json").write_text(json.dumps({"name": "kaixin-super-scholar", "type": "module", "main": "src/entry.mjs"}))
        profile = self.root / "isolated-synthetic-profile"
        profile.mkdir()
        (profile / ".launcher-migration-synthetic.json").write_text('{"synthetic":true}')
        # These disposable Ed25519 signatures are only for this fixture, never published.
        signed = json.loads(node("""
          import {generateKeyPairSync, sign} from 'node:crypto';
          const {canonicalManifest} = await import(process.env.BUNDLES);
          const {privateKey,publicKey}=generateKeyPairSync('ed25519');
          const arch=process.env.TARGET.split('-')[1];
          const platform=process.env.TARGET.startsWith('windows-')?'win32':'darwin';
          const full=(id,t)=>({formatVersion:1,protocolVersion:1,platform,arch,coreVersion:'1.7.1',
            runtimeId:`1.7.1-${id}-${arch}`,commit:id==='77f2ba387'?'77f2ba387713d23ef6af9897d393d24d84e421be':'fixture',
            builtAt:t,archive:`fixture-${id}.tar.gz`,sha256:'0'.repeat(64)});
          const seed=full('77f2ba387',1),base=full(process.env.BASE,2);
          const active={...full('fixture-current',3),baseRuntimeId:base.runtimeId};
          for(const m of [seed,base,active])m.signature=sign(null,Buffer.from(canonicalManifest(m)),privateKey).toString('base64');
          console.log(JSON.stringify({seed,base,active,publicKey:publicKey.export({type:'spki',format:'pem'})}));
        """, TARGET=target, BASE=active_base, BUNDLES=(shell / "src/bundles.mjs").as_uri()))
        (shell / "assets/runtime-public.pem").write_text(signed["publicKey"])
        seed = self.root / "original-signed-seed.json"
        seed.write_text(json.dumps(signed["seed"], indent=4) + "\n")
        (profile / "active.json").write_text(json.dumps(signed["active"]))
        for m in (signed["base"], signed["active"]):
            directory = profile / "runtimes" / m["runtimeId"]
            directory.mkdir(parents=True)
            (directory / "installed.json").write_text(json.dumps(m))
        base = profile / "runtimes" / signed["base"]["runtimeId"]
        current = profile / "runtimes" / signed["active"]["runtimeId"]
        files = [base / p for p in (["python/python.exe", "node/node.exe"] if target.startswith("windows-") else ["python/bin/python3", "node/bin/node"])]
        files += [current / "core/deeptutor_cli/main.py", current / "web/server.js", base / "core/deeptutor_cli/main.py", base / "web/server.js"]
        for file in files:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("SYNTHETIC FIXTURE; not executable")
        for folder in ("seed", "update"):
            p = package.resources(app, target) / folder
            p.mkdir()
            (p / "runtime.json").write_text('{"not":"a permitted baseline"}')
            (p / "large-archive.tar.gz").write_text("MUST NOT APPEAR IN PAYLOAD")
        settings = profile / "workspace/data/user/settings"
        settings.mkdir(parents=True)
        (settings / "providers.json").write_text('{"key":"SYNTHETIC-NOT-A-REAL-KEY"}')
        with sqlite3.connect(profile / "workspace/learning.db") as db:
            db.execute("create table chats (text text)")
            db.execute("insert into chats values ('synthetic chat kept')")
            db.execute("create table tasks (title text)")
            db.execute("insert into tasks values ('synthetic task kept')")
        return app, profile, seed, signed

    def stage(self, target="macos-x64", active_base="77f2ba387"):
        app, profile, seed, signed = self.fixture(target, active_base)
        stage = self.root / ("staged.app" if target.startswith("macos-") else "staged")
        shell = package.stage_app(app, stage, target, seed)
        root = stage / "Contents" if target.startswith("macos-") else stage
        inventory = json.loads(node("const {tree}=await import(process.env.HELPER); console.log(JSON.stringify(await tree(process.env.ROOT)));",
                                    HELPER=(shell / "launcher-migration-check.mjs").as_uri(), ROOT=str(root)))
        (shell / "launcher-migration-payload.json").write_text(json.dumps({"target": target, "files": inventory}))
        args = [NODE, shell / "launcher-migration-check.mjs", "--profile", profile, "--target", target,
                "--require-isolated", "--package-preflight"]
        return app, stage, profile, seed, signed, args

    def test_all_targets_strip_archives_and_preserve_seed_bytes(self):
        for target in sorted(package.TARGETS):
            with self.subTest(target=target), tempfile.TemporaryDirectory(dir=self.root) as temp:
                original = self.root
                self.root = Path(temp)
                app, stage, profile, seed, _, args = self.stage(target)
                before = verify_profile.profile_snapshot(profile)
                check = json.loads(package.run(args))
                self.assertTrue(check["existingRuntimeReused"])
                res = package.resources(stage, target)
                self.assertEqual((res / "seed/runtime.json").read_bytes(), seed.read_bytes())
                self.assertEqual([p.name for p in (res / "seed").iterdir()], ["runtime.json"])
                self.assertFalse((res / "update").exists())
                self.assertTrue((package.resources(app, target) / "update/large-archive.tar.gz").exists())
                self.assertTrue(verify_profile.compare(before, verify_profile.profile_snapshot(profile))["passed"])
                self.root = original

    def test_newer_042_profile_does_not_require_old77_runtime(self):
        _, _, profile, _, _, args = self.stage(active_base="04276f68a")
        self.assertFalse((profile / "runtimes/1.7.1-77f2ba387-x64").exists())
        self.assertIn('"passed":true', package.run(args))

    def test_missing_native_base_rejected(self):
        _, _, profile, _, signed, args = self.stage()
        shutil.rmtree(profile / "runtimes" / signed["base"]["runtimeId"])
        with self.assertRaises(subprocess.CalledProcessError):
            package.run(args)

    def test_forged_active_signature_rejected(self):
        _, _, profile, _, signed, args = self.stage()
        signed["active"]["builtAt"] += 1
        (profile / "active.json").write_text(json.dumps(signed["active"]))
        with self.assertRaises(subprocess.CalledProcessError):
            package.run(args)

    def test_unmarked_profile_rejected(self):
        _, _, profile, _, _, args = self.stage()
        (profile / ".launcher-migration-synthetic.json").unlink()
        with self.assertRaises(subprocess.CalledProcessError):
            package.run(args)

    def test_payload_tampering_rejected(self):
        _, stage, _, _, _, args = self.stage()
        (package.resources(stage, "macos-x64") / "app/src/main.mjs").write_text("tampered")
        with self.assertRaises(subprocess.CalledProcessError):
            package.run(args)

    def test_output_overlap_rejected(self):
        with self.assertRaises(ValueError):
            package.reject_overlap(self.root, self.root / "profile", self.root / "out")

    def test_external_app_symlink_rejected(self):
        app, _, baseline, _ = self.fixture()
        (app / "outside-link").symlink_to(self.root / "original-signed-seed.json")
        with self.assertRaises(ValueError):
            package.stage_app(app, self.root / "bad.app", "macos-x64", baseline)

    def test_profile_snapshot_detects_lost_chat_or_key(self):
        _, profile, _, _ = self.fixture()
        before = verify_profile.profile_snapshot(profile)
        with sqlite3.connect(profile / "workspace/learning.db") as db:
            db.execute("delete from chats")
        (profile / "workspace/data/user/settings/providers.json").write_text('{}')
        result = verify_profile.compare(before, verify_profile.profile_snapshot(profile))
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["problems"]), 2)

    def test_real_update_module_callable_offline(self):
        target = "windows-x64" if os.name == "nt" else ("macos-x64" if os.uname().machine == "x86_64" else "macos-arm64")
        app, _, _, signed = self.fixture(target)
        value = node("""
          import assert from 'node:assert/strict';
          const {findReleaseUpdate}=await import(process.env.MODULE);
          const current=JSON.parse(process.env.CURRENT); let calls=0;
          const response=await findReleaseUpdate(process.env.TARGET,current,process.env.KEY,async(url)=>{
            calls++;
            if(String(url).endsWith('/tags/core-updates'))return new Response(JSON.stringify({tag_name:'core-updates',draft:false,assets:[{id:1,state:'uploaded',name:`runtime-${process.env.TARGET}.json`}]}));
            assert(String(url).endsWith('/assets/1'));return new Response(JSON.stringify(current));
          });
          assert.equal(response,null);assert.equal(calls,2);console.log('offline update route callable');
        """, MODULE=(package.resources(app, target) / "app/src/release-updates.mjs").as_uri(),
          CURRENT=json.dumps(signed["active"]), KEY=signed["publicKey"], TARGET=target)
        self.assertIn("callable", value)

    def test_wrong_executable_architecture_rejected(self):
        app = self.root / "arm.app"
        exe = app / ("Contents/MacOS/" + package.APP)
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + b"\0" * 56)
        package.verify_executable(app, "macos-arm64")
        with self.assertRaises(ValueError):
            package.verify_executable(app, "macos-x64")

    def test_production_freeze_rejects_fixture_trust_key(self):
        app, _, _, _ = self.fixture()
        with self.assertRaises(ValueError):
            package.verify_shell(app, "macos-x64", package.read_json(HERE / "frozen-shell.json"))

    def test_authentic_baselines_verify_with_production_public_key(self):
        result = node("""
          import assert from 'node:assert/strict';
          import {readFile} from 'node:fs/promises';
          import {createHash} from 'node:crypto';
          const {verifyManifest}=await import(process.env.BUNDLES);
          const key=await readFile(process.env.PUBLIC_KEY,'utf8');
          const origin=JSON.parse(await readFile(`${process.env.BASELINES}/provenance.json`,'utf8'));
          for(const row of origin.manifests){
            const raw=await readFile(`${process.env.BASELINES}/${row.file}`);
            assert.equal(createHash('sha256').update(raw).digest('hex'),row.sha256);
            const arch=row.target.endsWith('arm64')?'arm64':'x64';
            const m=verifyManifest(JSON.parse(raw.toString('utf8')),key,arch,row.target.startsWith('macos')?'darwin':'win32');
            assert(!m.baseRuntimeId);assert.equal(m.runtimeId,`1.7.1-77f2ba387-${arch}`);
          }
          assert.equal(origin.manifests.length,3);console.log('three original signatures verified');
        """, BUNDLES=(SOURCE / "src/bundles.mjs").as_uri(), PUBLIC_KEY=str(SOURCE / "assets/runtime-public.pem"), BASELINES=str(HERE / "baselines"))
        self.assertIn("three original signatures verified", result)


if __name__ == "__main__":
    unittest.main(argv=[__file__, *REST])
