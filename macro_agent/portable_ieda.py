"""Pinned server-equivalent iEDA profile, shared by local DSH and CLI flows."""
import json
from pathlib import Path

IMAGE = 'sha256:1dc9f36f7e5a22686428945bba1de7f484bb10042468637c21225079060ddeb3'
BINARY_SHA256 = 'd9ae28962bf622f1139e2b438c6f69deb646d93a48ece783da80a082d607694a'
VERSION = 'ieda-server-d9ae2896-v1'
ENV = {'IEDA_RT_BEST_EFFORT':'0', 'IEDA_RT_NATIVE_LAYER_GRAPH':'0',
       'IEDA_RT_SR_LOCAL_PARALLEL':'0', 'LC_ALL':'C'}


def adapt_placement_config(path):
    """Adapt only an attempt's config; frozen case and PDK are never modified."""
    path=Path(path)
    data=json.loads(path.read_text(encoding='utf-8'))
    pl=data['PL']
    pl.pop('MP',None)  # Old macro-placer settings are invalid in this build.
    pl.setdefault('info_iter_num',10)
    pl['GP']['Density'].setdefault('is_adaptive_bin',0)
    # Registered GCD fixtures are tiny; use the server small-case grid profile.
    pl['GP']['Density'].update(target_density=0.6,bin_cnt_x=16,bin_cnt_y=16)
    path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    for config in path.parent.glob('*.json'):
        text=config.read_text(encoding='utf-8')
        text=text.replace('${RESULT_DIR}','/work/result').replace('${CONFIG_DIR}','/work/config').replace('$CONFIG_DIR','/work/config')
        config.write_text(text,encoding='utf-8')
