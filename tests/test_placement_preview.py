from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree

from macro_agent.task_artifacts import render


class PreviewLayersTest(unittest.TestCase):
    def test_filters_by_lef_class_and_preserves_source_def(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            lef = folder / "cells.lef"
            lef.write_text("".join(
                f"MACRO {name}\n  CLASS {kind} ;\n  SIZE 1 BY 2 ;\nEND {name}\n"
                for name, kind in [("gap", "CORE SPACER"), ("fill_named_logic", "CORE"),
                                   ("memory", "BLOCK"), ("tap", "CORE WELLTAP")]
            ))
            src = folder / "input.def"
            src.write_text("""DESIGN example ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 10000 10000 ) ;
COMPONENTS 4 ;
- a gap + PLACED ( 1000 1000 ) N ;
- b fill_named_logic + PLACED ( 2000 1000 ) N ;
- c memory + FIXED ( 3000 1000 ) N ;
- d tap + PLACED ( 4000 1000 ) N ;
END COMPONENTS
PINS 1 ;
- in + NET in + PLACED ( 1000 0 ) N ;
END PINS
END DESIGN
""")
            original = src.read_bytes()
            svg = folder / "placement.svg"
            receipt = render(src, [lef], svg)
            tree = ElementTree.parse(svg)
            self.assertEqual([n.text for n in tree.findall(".//{*}g/{*}title")], ["b", "c", "d"])
            self.assertEqual(receipt["hidden_spacers"], 1)
            self.assertFalse(tree.findall(".//{*}circle"))
            self.assertEqual(src.read_bytes(), original)
