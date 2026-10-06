import torch
import timm
import os

model_path = os.path.expanduser("~/models/virchow2")

model = timm.create_model(
    "hf_hub:paige-ai/Virchow2",
    pretrained=True,
    pretrained_cfg_overlay=dict(file=os.path.join(model_path, "pytorch_model.bin")),
    mlp_layer=timm.layers.SwiGLUPacked,
    act_layer=torch.nn.SiLU,
)
model.eval()

dummy = torch.randn(1, 3, 224, 224)
with torch.no_grad():
    output = model.forward_features(dummy)

print("output shape:", output.shape)
