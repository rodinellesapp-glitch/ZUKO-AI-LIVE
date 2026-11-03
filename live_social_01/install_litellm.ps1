$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $root 'vendor\litellm_runtime'
$requirements = Join-Path $root 'requirements-litellm.txt'
python -m pip install --disable-pip-version-check --no-warn-script-location --target $target -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'LiteLLM installation failed; the application files were not changed by this installer.' }
python -c "import os,sys; os.environ['LITELLM_LOCAL_MODEL_COST_MAP']='True'; sys.path.insert(0, r'$target'); from importlib.metadata import version; from litellm import acompletion; print('LiteLLM', version('litellm'))"
if ($LASTEXITCODE -ne 0) { throw 'LiteLLM import check failed in the isolated target.' }
