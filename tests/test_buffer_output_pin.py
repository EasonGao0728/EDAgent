import copy
import unittest
from macro_agent.aes_transforms import check


class BufferOutputPinTests(unittest.TestCase):
    def fixture(self):
        pin="out + NET n + DIRECTION OUTPUT + PLACED ( 2 3 ) N"
        before={"design":"d","units":2000,"die":[0,0,100,100],
                "pins":{"out":pin},"components":{"driver":{"master":"GATE","placement":None}},
                "nets":{"n":[("driver","Y"),("PIN","out")]}}
        after=copy.deepcopy(before)
        after["components"]["buf"]={"master":"BUF_X4","placement":None}
        after["pins"]["out"]=pin.replace("+ NET n ","+ NET buffered ")
        after["nets"]={"n":[("driver","Y"),("buf","A")],"buffered":[("buf","Z"),("PIN","out")]}
        return before,after

    def test_approved_buffer_may_rename_output_net(self):
        before,after=self.fixture()
        self.assertTrue(check(before,after,"fanout",{"BUF_X4":("A","Z")})["passed"])
        after["pins"]["out"]=after["pins"]["out"].replace("2 3","2 4")
        self.assertIn("changed_pins",check(before,after,"fanout",{"BUF_X4":("A","Z")})["errors"])

    def test_stale_pin_net_or_disconnected_buffer_is_rejected(self):
        before,after=self.fixture()
        after["pins"]["out"]=before["pins"]["out"]
        self.assertIn("pin_net_declaration_mismatch:out",check(before,after,"cts",{"BUF_X4":("A","Z")})["errors"])
        before,after=self.fixture()
        after["nets"]["buffered"].remove(("buf","Z"))
        self.assertFalse(check(before,after,"fanout",{"BUF_X4":("A","Z")})["passed"])


if __name__=="__main__":
    unittest.main()
