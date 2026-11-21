import unittest
from macro_agent.case_readiness import fits_budget


class AdmissionBudgetTests(unittest.TestCase):
    def test_extended_historical_route_cannot_qualify_default_budget(self):
        current={"cpu_threads":4,"memory_gb":8,"container_seconds":5400,
                 "host_seconds":5420,"routing_seconds":5400,"wall_seconds":7200}
        state={"contract":{"budget":dict(current,routing_seconds=21600,
                                            container_seconds=21600,host_seconds=21620)},
               "results":{"routing":{"seconds":11363.61}}}
        self.assertFalse(fits_budget(state,current))
        state["contract"]["budget"]=dict(current)
        self.assertFalse(fits_budget(state,current))
        state["results"]["routing"]["seconds"]=1200
        self.assertTrue(fits_budget(state,current))
        state["contract"]["budget"]["cpu_threads"]=8
        self.assertFalse(fits_budget(state,current))


if __name__=="__main__":
    unittest.main()
