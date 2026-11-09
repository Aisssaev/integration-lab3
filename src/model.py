"""Легка згорткова мережа для розпізнавання ключових слів (та сама архітектура, що в ЛР №1)."""
import torch
from torch import nn

ARCHITECTURE = "KeywordCNN: 4×[Conv3×3-BN-ReLU-MaxPool] (16-32-64-128) + GAP + Dropout + FC"


def _block(c_in: int, c_out: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(c_in, c_out, kernel_size=3, padding=1, bias=False),
        nn.BatchNorm2d(c_out),
        nn.ReLU(inplace=True),
        nn.MaxPool2d(2),
    )


class KeywordCNN(nn.Module):
    def __init__(self, n_classes: int, channels: tuple[int, ...] = (16, 32, 64, 128)) -> None:
        super().__init__()
        layers, c_in = [], 1
        for c_out in channels:
            layers.append(_block(c_in, c_out))
            c_in = c_out
        self.features = nn.Sequential(*layers)
        self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.3), nn.Linear(c_in, n_classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: [B, N_MELS, frames] нормалізована лог-Mel -> логіти [B, n_classes]."""
        return self.head(self.features(x.unsqueeze(1)))


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
