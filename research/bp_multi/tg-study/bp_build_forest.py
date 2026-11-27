"""Build the standalone native route-tree reader against the existing personal iRT build."""
from pathlib import Path
import json,shlex,subprocess
from bp_short_study import WORK
build=Path('/srv/edagent/bp-multi-official-build-v1/build')
unit=next(i for i in json.loads((build/'compile_commands.json').read_bytes()) if i['file'].endswith('/DetailedRouter.cpp'))
args=shlex.split(unit['command']); args[args.index('-o')+1]=str(WORK/'forest.o')
args[args.index('-c')+1]=str(Path(__file__).resolve().with_name('bp_short_forest.cpp'))
subprocess.run(args,cwd=build,check=True)
libs=shlex.split(subprocess.check_output(['ninja','-t','commands','iEDA'],cwd=build,text=True).splitlines()[-1])
libs=libs[libs.index('-o')+2:]; libs=libs[:libs.index('&&')] if '&&' in libs else libs
subprocess.run([args[0],str(WORK/'forest.o'),'-o',str(WORK/'forest'),*libs],cwd=build,check=True)
