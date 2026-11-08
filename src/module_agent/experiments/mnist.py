"""A reviewed M5 pilot profile. Dependency/data preparation is never implicit."""

import ast
import json
from pathlib import Path
from module_agent.experiments import workspace as storage

from module_agent.experiments.domain import ExperimentBudget, ExperimentPlan
from module_agent.experiments.workspace import (
    ExperimentWorkspace,
    code_files,
    dataset_files,
    fingerprint,
)


def build_m5_plan(
    workspace: ExperimentWorkspace,
    *,
    repository: Path,
    dataset: Path,
    image: str,
    budget: ExperimentBudget,
    patch_note: str,
    seed: int = 0,
) -> ExperimentPlan:
    """Hash prepared local inputs without importing or running repository code."""
    repository = workspace.input_directory(repository)
    dataset = workspace.input_directory(dataset)
    storage.verify_commit(repository, "a21bd677f62fcdee77c82419b898d421682e3fd2")
    sources = code_files(repository)
    for path, content in sources.items():
        tree = ast.parse(content, filename=path)
        if any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "np"
            and node.attr == "int"
            for node in ast.walk(tree)
        ):
            raise ValueError(
                "Apply and record the reviewed np.int compatibility fix before planning"
            )
    return ExperimentPlan(
        repository_path=repository,
        dataset_path=dataset,
        source_sha256=fingerprint(sources),
        dataset_sha256=fingerprint(dataset_files(dataset)),
        image=image,
        budget=budget,
        source_patch_note=patch_note,
        seed=seed,
    )


def environment_command() -> list[str]:
    """Check the actual isolated runtime, CUDA kernel and model, not just nvidia-smi."""
    return [
        "python",
        "-u",
        "-c",
        """import importlib.metadata,json,platform
import numpy as np
import torch
import torchvision
import torchsummary
from models.modelM5 import ModelM5
assert platform.python_version().startswith('3.11.'), 'Expected Python 3.11'
assert torch.__version__.split('+')[0]=='2.7.1', 'Unexpected torch version'
assert torchvision.__version__.split('+')[0]=='0.22.1', 'Unexpected torchvision version'
assert np.__version__=='1.26.4', 'Unexpected numpy version'
assert torch.version.cuda=='12.8', 'Expected CUDA 12.8 build'
assert torch.cuda.is_available() and torch.cuda.device_count()==1, 'Exactly one CUDA device required'
assert (torch.ones(1,device='cuda')+1).item()==2, 'CUDA kernel probe failed'
count=sum(p.numel() for p in ModelM5().parameters() if p.requires_grad)
assert count==1128180, 'Model parameter count differs from reviewed M5'
print('MODULE_AGENT_ENV='+json.dumps({'python':platform.python_version(),'torch':torch.__version__,'torchvision':torchvision.__version__,'numpy':np.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),'parameters':count,'pillow':importlib.metadata.version('Pillow'),'torchsummary':importlib.metadata.version('torchsummary')}))""",
    ]


def train_command(plan: ExperimentPlan) -> list[str]:
    return [
        "python",
        "-u",
        "train.py",
        "--seed",
        str(plan.seed),
        "--trials",
        "1",
        "--epochs",
        str(plan.epochs),
        "--kernel_size",
        "5",
        "--gpu",
        "0",
        "--logdir",
        "pilot",
    ]


def evaluation_command(plan: ExperimentPlan) -> list[str]:
    """Independently count every test example; never deserialize weights on the host."""
    script = r"""import hashlib,json,pathlib
import torch
from datasets import MnistDataset
from models.modelM5 import ModelM5
assert torch.cuda.is_available(), 'CUDA is required; no silent CPU fallback'
root=pathlib.Path('../logs/pilot')
checkpoint=root/('model%03d.pth'%SEED)
model=ModelM5().to('cuda')
model.load_state_dict(torch.load(checkpoint,map_location='cuda',weights_only=True))
model.eval()
dataset=MnistDataset(training=False,transform=None)
assert len(dataset)==10000, 'Unexpected test split'
loader=torch.utils.data.DataLoader(dataset,batch_size=100,shuffle=False,num_workers=0)
seen=correct=0
wrong=[]
with torch.no_grad():
    for inputs,labels in loader:
        prediction=model(inputs.to('cuda')).argmax(dim=1).cpu()
        matches=prediction.eq(labels.to(dtype=torch.int64))
        wrong.extend(seen+int(i) for i in torch.nonzero(~matches).flatten())
        correct+=int(matches.sum())
        seen+=len(labels)
assert seen==10000 and correct+len(wrong)==seen
(root/('wrong%03d.txt'%SEED)).write_text(''.join('%d\n'%i for i in wrong))
print('MODULE_AGENT_EVAL='+json.dumps({'evaluated_samples':seen,'correct':correct,'wrong':len(wrong),'accuracy_percent':100*correct/seen,'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()}))"""
    return ["python", "-u", "-c", "SEED=" + str(plan.seed) + "\n" + script]


def structured_stdout(stdout: str, prefix: str) -> dict[str, object]:
    lines = [
        line[len(prefix) :] for line in stdout.splitlines() if line.startswith(prefix)
    ]
    if len(lines) != 1:
        raise ValueError("Missing or ambiguous structured experiment evidence")
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        raise ValueError("Experiment evidence must be an object")
    return value
