from typing import Dict, Union, Optional, Tuple, Any, Sequence, cast

import gym
import torch
from torch import nn

from allenact.algorithms.onpolicy_sync.policy import (
    ActorCriticModel,
    DistributionType,
)
from allenact.base_abstractions.misc import ActorCriticOutput, Memory
from allenact_plugins.gym_plugin.gym_distributions import GaussianDistr
from allenact.base_abstractions.distributions import CategoricalDistr


class MemorylessActorCritic(ActorCriticModel[GaussianDistr]):
    """ActorCriticModel for gym tasks with continuous control in the range [-1,
    1]."""

    def __init__(
        self,
        input_uuid: str,
        action_space: gym.spaces.Box,
        observation_space: gym.spaces.Dict,
        action_std: float = 0.5,
        mlp_hidden_dims: Sequence[int] = (64, 32),
    ):
        super().__init__(action_space, observation_space)

        self.input_uuid = input_uuid

        assert len(observation_space[self.input_uuid].shape) == 1
        state_dim = observation_space[self.input_uuid].shape[0]
        assert len(action_space.shape) == 1
        action_dim = action_space.shape[0]

        mlp_hidden_dims = (state_dim,) + tuple(mlp_hidden_dims)

        # action mean range -1 to 1
        self.actor = nn.Sequential(
            *self.make_mlp_hidden(nn.Tanh, *mlp_hidden_dims),
            nn.Linear(32, action_dim),
            nn.Tanh(),
        )

        # critic
        self.critic = nn.Sequential(
            *self.make_mlp_hidden(nn.Tanh, *mlp_hidden_dims), nn.Linear(32, 1),
        )

        # maximum standard deviation
        self.register_buffer(
            "action_std",
            torch.tensor([action_std] * action_dim).view(1, 1, -1),
            persistent=False,
        )

    @staticmethod
    def make_mlp_hidden(nl, *dims):
        res = []
        for it, dim in enumerate(dims[:-1]):
            res.append(nn.Linear(dim, dims[it + 1]),)
            res.append(nl())
        return res

    def _recurrent_memory_specification(self):
        return None

    def forward(  # type:ignore
        self,
        observations: Dict[str, Union[torch.FloatTensor, Dict[str, Any]]],
        memory: Memory,
        prev_actions: Any,
        masks: torch.FloatTensor,
    ) -> Tuple[ActorCriticOutput[DistributionType], Optional[Memory]]:
        means = self.actor(observations[self.input_uuid])
        values = self.critic(observations[self.input_uuid])

        return (
            ActorCriticOutput(
                cast(DistributionType, GaussianDistr(loc=means, scale=self.action_std)),
                values,
                {},
            ),
            None,  # no Memory
        )


class ContrastiveConvolutionalActorCritic(ActorCriticModel[GaussianDistr]):
    """ActorCriticModel for gym tasks with continuous control in the range [-1,
    1]."""

    def __init__(
        self,
        input_uuid: str,
        action_space: gym.spaces.Discrete,
        observation_space: gym.spaces.Dict,
        mlp_hidden_dims: Sequence[int] = (64, 32),
    ):
        super().__init__(action_space, observation_space)

        self.input_uuid = input_uuid

        self.encoder = nn.Sequential(
            nn.Conv2d(3, 16, (8,8), stride=4),
            nn.ReLU(),
            nn.Conv2d(16, 32, (4,4), stride=2),
            nn.ReLU(),
            nn.Flatten(),
            nn.Linear(2592, 2048),
            nn.ReLU(),
            # nn.Linear(2816, 2048),
            # nn.ReLU(),
        )

        state_dim = 2048
        action_dim = action_space.n
        mlp_hidden_dims = (state_dim,) + tuple(mlp_hidden_dims)

        # action mean range -1 to 1
        self.actor = nn.Sequential(
            *self.make_mlp_hidden(nn.Tanh, *mlp_hidden_dims),
            nn.Linear(32, action_dim),
        )

        # critic
        self.critic = nn.Sequential(
            *self.make_mlp_hidden(nn.Tanh, *mlp_hidden_dims), nn.Linear(32, 1),
        )

    @staticmethod
    def make_mlp_hidden(nl, *dims):
        res = []
        for it, dim in enumerate(dims[:-1]):
            res.append(nn.Linear(dim, dims[it + 1]),)
            res.append(nl())
        return res

    def _recurrent_memory_specification(self):
        return None

    def forward(  # type:ignore
        self,
        observations: Dict[str, Union[torch.FloatTensor, Dict[str, Any]]],
        memory: Memory,
        prev_actions: Any,
        masks: torch.FloatTensor,
    ) -> Tuple[ActorCriticOutput[DistributionType], Optional[Memory]]:
        osizes = observations[self.input_uuid].shape
        observation = (observations[self.input_uuid]).float().view(osizes[0]*osizes[1], *osizes[2:])
        # Switch from N x H x W x C to N x C x H x W
        observation = observation.permute(0, 3, 1, 2)
        embedding = self.encoder(observation)
        logits = self.actor(embedding).view(osizes[0], osizes[1], -1)
        values = self.critic(embedding).view(osizes[0], osizes[1], -1)

        return (
            ActorCriticOutput(
                distributions=CategoricalDistr(logits=logits),
                values=values,
                extras={},
            ),
            None,  # no Memory
        )
