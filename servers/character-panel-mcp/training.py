"""
training.py — Tier 3: per-character LoRA baking via kohya-ss/sd-scripts.

Strongest of the three consistency tiers (ARCHITECTURE.md §8b.2): train a small
SD1.5 LoRA on a character's reference set. One-time cost per character (~30-90 min
on a 3060-class GPU), buys the best consistency available locally. Needs its own
separate install — kohya-ss/sd-scripts is not a ComfyUI custom node, it's a
standalone training toolkit with its own venv; see README.md's Tier-3 setup steps.

A 30-90 min run cannot block an MCP tool call, so this is async by construction:
`bake()` prepares a dataset, launches `accelerate launch train_network.py` as a
DETACHED background process (same pattern workflow.py uses to auto-launch
ComfyUI), and returns immediately. `status()` polls it (and finalizes the result
into the character's bible + ComfyUI's models/loras/ the first time it observes
completion). `cancel()` kills it.

Dataset/captioning: a single fixed caption per image (a rare instance token +
class word + the character's own description/tags from the bible) — not
per-image auto-captioning (e.g. BLIP). This is a deliberate scope decision, not a
gap: trigger-word + fixed-caption is a standard, well-supported approach for
single-subject character LoRAs, and avoids adding a captioning model dependency.

This module is pure orchestration — it never talks to ComfyUI directly. Once a
LoRA is baked, it plugs into workflow.py's existing `lora=` mechanism with zero
new graph code (see characters.set_character_lora).

Style base: by default, bakes merge the Niji V5 Style LoRA into the checkpoint
BEFORE training (sd-scripts' `--base_weights`/`--base_weights_multiplier`, which
merges an existing LoRA into the base model prior to training a new one on top —
not the same as generate_character_pose's `lora=` param, which applies a style
LoRA at generation time). This means a baked character LoRA carries the Niji V5
look with it, matching the ecosystem's per-project style pool
(webcomic-background-mcp v1.7.0 / this server's own generate_character_pose).
Pass style_lora="" to bake against a plain checkpoint instead.
"""

import os
import re
import json
import time
import shutil
import subprocess
import datetime

import characters
import workflow

_HERE = os.path.dirname(os.path.abspath(__file__))

# kohya-ss/sd-scripts install location and the Python that has its deps installed.
KOHYA_DIR = os.environ.get("WEBCOMIC_CHAR_KOHYA_DIR", r"C:\AI\sd-scripts")
KOHYA_PYTHON = os.environ.get("WEBCOMIC_CHAR_KOHYA_PYTHON",
                              os.path.join(KOHYA_DIR, "venv", "Scripts", "python.exe"))
# ComfyUI's models/ root (a real filesystem path — unlike workflow.py's Tier-1/2
# generation, which only ever passes filenames through ComfyUI's own HTTP API,
# training needs to read the checkpoint off disk and write the output LoRA where
# ComfyUI's LoraLoader node will find it).
COMFY_MODELS = os.environ.get("WEBCOMIC_CHAR_COMFY_MODELS",
                              os.path.join(workflow.COMFY_DIR, "ComfyUI", "models"))
# Default style baked into every character LoRA — merged into the checkpoint via
# sd-scripts' --base_weights before training starts. Same file the background
# server documents as an optional style choice; here it's the Tier-3 default so
# baked characters match a project's Niji-V5-styled plates out of the box. Pass
# style_lora="" to bake() to skip this and train against a plain checkpoint.
STYLE_LORA = os.environ.get("WEBCOMIC_CHAR_BAKE_STYLE_LORA", "NijiV5Style.safetensors")
STYLE_LORA_MULTIPLIER = float(os.environ.get("WEBCOMIC_CHAR_BAKE_STYLE_LORA_MULTIPLIER", "1.0"))


class TrainingError(RuntimeError):
    pass


def _lora_dir(character_id: str, project: str | None) -> str:
    return os.path.join(characters._character_dir(character_id, project), "lora")


def _job_path(character_id: str, project: str | None) -> str:
    return os.path.join(_lora_dir(character_id, project), "job.json")


def _load_job(character_id: str, project: str | None) -> dict | None:
    path = _job_path(character_id, project)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_job(character_id: str, project: str | None, job: dict) -> None:
    path = _job_path(character_id, project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _tail(path: str, n: int = 20) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[-n:])


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True, timeout=10)
            return str(pid) in out.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=10)
    else:
        import signal
        os.kill(pid, signal.SIGTERM)


def _prepare_dataset(character_id: str, project: str | None, repeats: int,
                     class_word: str) -> tuple[str, int]:
    """Build a kohya-ss dataset folder for this character. Returns
    (train_data_dir, num_images). train_data_dir is the PARENT of the
    repeat-prefixed subfolder (kohya scans it for `<repeats>_<name>/`
    subfolders) — pass this to --train_data_dir, not the subfolder itself."""
    entry = characters.get_character(character_id, project)
    if entry is None:
        raise TrainingError(
            f"No character '{character_id}' in project "
            f"'{characters._slug(project or characters.DEFAULT_PROJECT)}'. Register it first."
        )
    ref_paths = entry.get("ref_paths", [])
    if not ref_paths:
        raise TrainingError(f"Character '{character_id}' has no reference images to train on.")

    char_id = characters._slug(character_id)
    train_data_dir = os.path.join(_lora_dir(character_id, project), "dataset")
    image_dir = os.path.join(train_data_dir, f"{repeats}_{char_id}")
    # Fresh dataset each bake — stale images from a smaller/older reference set
    # (before the bootstrap loop added more) shouldn't silently linger.
    if os.path.isdir(image_dir):
        shutil.rmtree(image_dir)
    os.makedirs(image_dir, exist_ok=True)

    try:
        from PIL import Image
        has_pil = True
    except ImportError:
        has_pil = False

    caption_parts = [char_id, class_word]
    if entry.get("description"):
        caption_parts.append(entry["description"])
    if entry.get("tags"):
        caption_parts.append(", ".join(entry["tags"]))
    caption = ", ".join(caption_parts)

    for i, ref_path in enumerate(ref_paths):
        dest_img = os.path.join(image_dir, f"img_{i:02d}.png")
        if has_pil:
            Image.open(ref_path).convert("RGB").save(dest_img)
        else:
            shutil.copyfile(ref_path, dest_img)
        with open(os.path.join(image_dir, f"img_{i:02d}.txt"), "w", encoding="utf-8") as f:
            f.write(caption)

    return train_data_dir, len(ref_paths)


def _build_command(train_data_dir: str, output_dir: str, output_name: str,
                   ckpt_path: str, resolution: int, network_dim: int,
                   network_alpha: int, learning_rate: float, max_train_epochs: int,
                   train_batch_size: int, mixed_precision: str,
                   base_weights: str | None = None,
                   base_weights_multiplier: float = 1.0) -> list[str]:
    """The accelerate-launch argument list for train_network.py. Uses
    `<python> -m accelerate.commands.launch` rather than assuming an `accelerate`
    console script is on PATH — only needs KOHYA_PYTHON to be correct.

    base_weights (verified sd-scripts flag): merges an existing LoRA into the
    base checkpoint BEFORE training starts — the mechanism behind baking the
    style LoRA into every character LoRA by default (see module docstring)."""
    script = os.path.join(KOHYA_DIR, "train_network.py")
    cmd = [
        KOHYA_PYTHON, "-m", "accelerate.commands.launch",
        "--num_cpu_threads_per_process", "1",
        script,
        "--pretrained_model_name_or_path", ckpt_path,
        "--train_data_dir", train_data_dir,
        "--output_dir", output_dir,
        "--output_name", output_name,
        "--resolution", str(resolution),
        "--network_module", "networks.lora",
        "--network_dim", str(network_dim),
        "--network_alpha", str(network_alpha),
        "--learning_rate", str(learning_rate),
        "--max_train_epochs", str(max_train_epochs),
        "--train_batch_size", str(train_batch_size),
        "--mixed_precision", mixed_precision,
        "--save_model_as", "safetensors",
        "--save_every_n_epochs", str(max_train_epochs),
        "--caption_extension", ".txt",
    ]
    if base_weights:
        cmd += ["--base_weights", base_weights,
               "--base_weights_multiplier", str(base_weights_multiplier)]
    return cmd


def bake(
    character_id: str,
    project: str | None = None,
    epochs: int = 10,
    repeats: int = 10,
    network_dim: int = 32,
    network_alpha: int = 16,
    learning_rate: float = 1e-4,
    resolution: int = 512,
    class_word: str = "person",
    model: str | None = None,
    train_batch_size: int = 1,
    mixed_precision: str = "fp16",
    style_lora: str | None = STYLE_LORA,
    style_lora_multiplier: float = STYLE_LORA_MULTIPLIER,
) -> dict:
    """Prepare the dataset and launch training as a detached background process.
    Returns immediately with the job info; poll with status().

    style_lora: merged into the checkpoint before training (sd-scripts
    --base_weights) so the baked character LoRA carries this style. Defaults to
    STYLE_LORA (Niji V5 Style) — pass "" to bake against a plain checkpoint."""
    if not os.path.isfile(KOHYA_PYTHON):
        raise TrainingError(
            f"kohya-ss Python not found at {KOHYA_PYTHON}. Set WEBCOMIC_CHAR_KOHYA_PYTHON "
            f"(or WEBCOMIC_CHAR_KOHYA_DIR) — see README.md's Tier-3 setup steps."
        )

    existing = _load_job(character_id, project)
    if existing and existing.get("state") == "training" and _pid_alive(existing.get("pid", -1)):
        raise TrainingError(
            f"A training job is already running for '{character_id}' "
            f"(started {existing.get('started_at')}). Cancel it first with "
            f"cancel_lora_training, or wait for it to finish."
        )

    model = model or workflow.DEFAULT_MODEL
    if model not in workflow.MODELS:
        raise TrainingError(f"Unknown model '{model}'. Options: {', '.join(workflow.MODELS)}")
    ckpt_path = os.path.join(COMFY_MODELS, "checkpoints", workflow.MODELS[model]["ckpt"])
    if not os.path.isfile(ckpt_path):
        raise TrainingError(
            f"Checkpoint not found at {ckpt_path}. Set WEBCOMIC_CHAR_COMFY_MODELS to "
            f"ComfyUI's models/ folder if this server isn't sharing webcomic-background-mcp's."
        )

    base_weights_path = None
    if style_lora:
        base_weights_path = os.path.join(COMFY_MODELS, "loras", style_lora)
        if not os.path.isfile(base_weights_path):
            raise TrainingError(
                f"Style LoRA not found at {base_weights_path}. Install it (see "
                f"webcomic-background-mcp's model table) or pass style_lora=\"\" "
                f"to bake against a plain checkpoint instead."
            )

    train_data_dir, num_images = _prepare_dataset(character_id, project, repeats, class_word)

    char_id = characters._slug(character_id)
    lora_dir = _lora_dir(character_id, project)
    output_dir = os.path.join(lora_dir, "output")
    output_name = f"character_{char_id}"
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(lora_dir, "train.log")

    command = _build_command(train_data_dir, output_dir, output_name, ckpt_path,
                             resolution, network_dim, network_alpha, learning_rate,
                             epochs, train_batch_size, mixed_precision,
                             base_weights_path, style_lora_multiplier)

    log_f = open(log_path, "w", encoding="utf-8")
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(command, cwd=KOHYA_DIR, creationflags=flags,
                                stdin=subprocess.DEVNULL, stdout=log_f, stderr=log_f,
                                close_fds=True)
    else:
        proc = subprocess.Popen(command, cwd=KOHYA_DIR, stdin=subprocess.DEVNULL,
                                stdout=log_f, stderr=log_f, start_new_session=True)
    log_f.close()

    job = {
        "state": "training",
        "character": char_id,
        "project": characters._slug(project or characters.DEFAULT_PROJECT),
        "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pid": proc.pid,
        "log_path": log_path,
        "output_dir": output_dir,
        "output_name": output_name,
        "expected_output": os.path.join(output_dir, f"{output_name}.safetensors"),
        "num_images": num_images,
        "epochs": epochs,
        "style_lora": style_lora or None,
        "command": command,
    }
    _save_job(character_id, project, job)
    return job


def status(character_id: str, project: str | None = None) -> dict:
    """Poll a training job. Finalizes (copies the LoRA into ComfyUI's
    models/loras/ and records it on the character's bible entry) the first time
    it observes the expected output file exists."""
    job = _load_job(character_id, project)
    if job is None:
        return {"state": "none"}

    if job["state"] == "training":
        output_exists = os.path.isfile(job["expected_output"])
        alive = _pid_alive(job["pid"])
        if output_exists:
            loras_dir = os.path.join(COMFY_MODELS, "loras")
            os.makedirs(loras_dir, exist_ok=True)
            dest_name = f"{job['output_name']}.safetensors"
            dest_path = os.path.join(loras_dir, dest_name)
            shutil.copyfile(job["expected_output"], dest_path)
            characters.set_character_lora(character_id, dest_name, project)
            job["state"] = "done"
            job["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            job["installed_lora"] = dest_name
            _save_job(character_id, project, job)
        elif not alive:
            job["state"] = "failed"
            job["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            _save_job(character_id, project, job)

    job["log_tail"] = _tail(job["log_path"])
    return job


def cancel(character_id: str, project: str | None = None) -> bool:
    """Kill a running training job. Returns False if there's nothing to cancel."""
    job = _load_job(character_id, project)
    if job is None or job.get("state") != "training":
        return False
    if _pid_alive(job["pid"]):
        _kill(job["pid"])
    job["state"] = "cancelled"
    job["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    _save_job(character_id, project, job)
    return True
