"""Capacity policy and resource reporting with synthetic input, without Docker writes."""
import ipaddress
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from test_platform_delivery import ConfigurationTests, load
from test_console_runtime import runtime

sampler = load("platform-sample")
capacity = sampler.config.capacity


class ProfileTests(ConfigurationTests):
    def profile(self, **changes):
        return self.config(version=2, profile="single-host-50-io", **changes)

    def test_v2_requires_named_profile_and_only_v2_accepts_64(self):
        self.assertEqual(self.profile(max_runtimes=64).max_runtimes, 64)
        for maximum in (0,65,True,50.0):
            with self.assertRaises(ValueError):
                self.profile(max_runtimes=maximum)
        with self.assertRaises(ValueError):
            self.config(max_runtimes=50)
        with self.assertRaises(ValueError):
            self.config(capacity_policy={})

    def test_shared_cpu_and_strict_memory_use_same_host_contract(self):
        cfg=self.profile(max_runtimes=50,capacity_policy={"cpu_mode":"shared","cpu_overcommit_factor":4})
        self.assertEqual(cfg.cpu_budget,41.5)
        self.assertEqual(cfg.memory_budget_mib,140544)
        result=sampler.assess(cfg,{"MemTotal":32*1024**3,"NCPU":16,"SwapTotal":1024**4},[],set())
        self.assertEqual(result["status"],"insufficient")
        self.assertEqual(len(result["failures"]),2)
        self.assertEqual(result["actual_load_validation"],"not_run")
        self.assertFalse(result["memory_includes_swap"])
        self.assertEqual(result["memory_shortfall_bytes"],105.25*1024**3)
        # Exact byte boundary, not rounded GiB display, controls admission.
        info={"MemTotal":cfg.memory_budget_mib*1024**2-1,"NCPU":64}
        self.assertEqual(capacity.evaluate(info,cfg.resource_budget)["status"],"insufficient")
        info["MemTotal"]+=1
        self.assertEqual(capacity.evaluate(info,cfg.resource_budget)["status"],"passed")

    def test_cpu_policy_is_explicit_finite_and_reserves_platform_caps(self):
        for value in ({"cpu_overcommit_factor":4},{"cpu_mode":"shared","cpu_overcommit_factor":float("nan")},
                      {"cpu_mode":"shared","cpu_reserve":2},{"host_memory_reserve_mib":True},
                      {"unknown":1}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.profile(capacity_policy=value)

    def test_concurrency_is_bounded_and_forwarded_peer_is_entry_cidr(self):
        cfg=self.profile()
        compose=load("platform-manage").compose_config(cfg)
        console=compose["services"]["console"]
        self.assertEqual(console["cpus"],2)
        self.assertEqual(console["mem_limit"],"2048m")
        self.assertEqual(console["memswap_limit"],"2048m")
        self.assertEqual(console["environment"]["FORWARDED_ALLOW_IPS"],"10.240.0.0/28")
        self.assertEqual(console["environment"]["PX_AUTH_RECHECK_SECONDS"],"2")
        self.assertEqual(console["environment"]["PX_HTTP_CONNECTIONS"],"64")
        for values in ({"auth_recheck_seconds":3},{"db_busy_ms":1001},{"db_workers":True},
                       {"sse_renew_seconds":10},{"http_connections":8},{"crypto_queue":0},
                       {"db_queue_seconds":0.5},{"http_keepalive":0},{"other":1}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                self.profile(concurrency=values)

    def test_new_config_requires_control_image_capability_before_start(self):
        cfg=self.profile()
        for labels in ({}, {"org.peixian.control.config.max":"1"}, {"org.peixian.control.config.max":"2oops"}):
            with self.assertRaisesRegex(ValueError,"configuration_incompatible"):
                cfg.verify_control_image(labels)
        cfg.verify_control_image({"org.peixian.control.config.max":"2"})
        self.config().verify_control_image({})

    def test_worker_budget_agrees_and_rejects_insufficient_engine(self):
        cfg=self.profile(max_runtimes=50,capacity_policy={"cpu_mode":"shared","cpu_overcommit_factor":4})
        manager=object.__new__(runtime.RuntimeManager)
        manager.maximum=cfg.max_runtimes
        manager.config_version=cfg.version
        manager.limits=cfg.resource_limits
        manager.control_resources=cfg.control_resources
        manager.capacity_policy=cfg.capacity_policy
        manager.deployment_id=cfg.deployment_id
        def docker(*args):
            return "" if args[0]=="ps" else json.dumps({"MemTotal":32*1024**3,"NCPU":16})
        manager.docker_run=docker
        with self.assertRaisesRegex(runtime.RuntimeFailure,"docker_memory_budget_exceeded"):
            manager.capacity("f"*32)
        manager.docker_run=lambda *args: "" if args[0]=="ps" else json.dumps({"MemTotal":cfg.memory_budget_mib*1024**2,"NCPU":64})
        manager.capacity("f"*32)


class NetworkTests(unittest.TestCase):
    def network(self,name,subnet,rid=None,deployment="synthetic"):
        labels={"peixian.deployment":deployment}
        if rid:
            labels["peixian.runtime_id"]=rid
        return {"Name":name,"Labels":labels,"IPAM":{"Config":[{"Subnet":subnet}]}}

    def test_50_requires_151_whole_subnets_and_foreign_overlap_is_unavailable(self):
        self.assertEqual(capacity.network_capacity("10.240.0.0/20",[],"synthetic",50)["required_subnets"],151)
        self.assertEqual(capacity.network_capacity("10.240.0.0/21",[],"synthetic",50)["status"],"insufficient")
        foreign=[self.network("foreign","10.240.0.0/21",deployment="other")]
        self.assertEqual(capacity.network_capacity("10.240.0.0/20",foreign,"synthetic",50)["status"],"insufficient")

    def test_existing_150_account_networks_are_counted_without_double_reservation(self):
        subnets=iter(ipaddress.ip_network("10.240.0.0/20").subnets(new_prefix=28))
        records=[self.network("synthetic-front",str(next(subnets)))]
        for number in range(50):
            rid=f"{number:032x}"
            for suffix in ("internal","management","egress"):
                records.append(self.network("px-"+rid+"-"+suffix,str(next(subnets)),rid))
        result=capacity.network_capacity("10.240.0.0/20",records,"synthetic",50)
        self.assertEqual(result["existing_owned_subnets"],151)
        self.assertEqual(result["missing_subnets"],0)
        self.assertEqual(result["status"],"passed")

    def test_paused_historical_accounts_and_new_identity_count(self):
        retained={f"{number:032x}" for number in range(90)}
        value=capacity.network_capacity("10.240.0.0/20",[],"synthetic",50,retained)
        self.assertEqual(value["required_subnets"],271)
        self.assertEqual(value["status"],"insufficient")

    def test_retained_owner_outside_pool_and_unknown_identity_are_not_reused(self):
        rid="a"*32
        records=[self.network("px-"+rid+"-internal","10.250.0.0/28",rid)]
        with self.assertRaisesRegex(ValueError,"outside_expected"):
            capacity.network_capacity("10.240.0.0/16",records,"synthetic",50)
        with self.assertRaises(ValueError):
            capacity.network_capacity("10.240.0.0/16",[],"synthetic",50,{"../escape"})


class ProbeTests(unittest.TestCase):
    def test_stat_units_and_missing_metrics_are_not_zero(self):
        value=sampler.stat_record({"MemUsage":"1.25GiB / 2GiB","CPUPerc":"15.2%","PIDs":"9"})
        self.assertEqual(value["docker_memory_usage_bytes"],int(1.25*1024**3))
        with self.assertRaises(sampler.SampleError):
            sampler.stat_record({"MemUsage":"N/A","CPUPerc":"N/A","PIDs":"--"})
        with patch.object(sampler,"command",side_effect=sampler.SampleError("unavailable")):
            self.assertEqual(sampler.cgroup("a"),{"cgroup":None,"cgroup_status":"unavailable"})

    def test_sample_redacts_identifiers_and_only_runs_read_operations(self):
        calls=[]
        identifier="a"*64
        def command(*args):
            calls.append(args)
            if args[1]=="ps":
                return identifier[:12]
            if args[1]=="inspect":
                return json.dumps({"id":identifier,"running":True,"oom_killed":False,"restart_count":0,"service":"agent"})
            if args[1]=="stats":
                return json.dumps({"ID":identifier[:12],"MemUsage":"100MiB / 2GiB","CPUPerc":"1%","PIDs":"2"})
            if args[1]=="exec":
                return json.dumps({"memory.current":100000000,"memory.peak":150000000,"memory.events":{"oom_kill":0}})
            self.fail("unexpected command")
        with patch.object(sampler,"command",side_effect=command):
            result=sampler.sample(SimpleNamespace(deployment_id="synthetic"),True)
        self.assertEqual(result["running_count"],1)
        self.assertEqual(result["containers"][0]["cgroup_status"],"available")
        self.assertNotIn(identifier,json.dumps(result))
        self.assertEqual({args[1] for args in calls},{"ps","inspect","stats","exec"})


if __name__ == "__main__":
    unittest.main()
