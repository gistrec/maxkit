from typing import Any


class FSMStorage:
    """
    In-memory storage of FSM state and data.

    State is keyed by ``user_id`` only, so a user shares the same state and
    data across every chat they talk to the bot in. In multi-chat/group bots
    a single user's flows in different chats will therefore collide; scope
    your own keys by chat if you need per-chat isolation.
    """

    def __init__(self):
        self.states: dict[int, Any] = {}
        self.data: dict[int, Any] = {}

    def get_state(self, user_id: int) -> Any:
        """
        Gets user's state
        """
        return self.states.get(user_id)

    def get_data(self, user_id: int) -> Any:
        """
        Gets user's data
        """
        return self.data.get(user_id)

    def change_state(self, user_id: int, new: Any):
        """
        Changes user's state
        """
        self.states[user_id] = new

    def change_data(self, user_id: int, new: Any):
        """
        Changes user's data
        """
        self.data[user_id] = new

    def clear_state(self, user_id: int) -> Any:
        """
        Clears user's state and returns it
        """
        return self.states.pop(user_id, None)

    def clear_data(self, user_id: int) -> Any:
        """
        Clears user's data and returns it
        """
        return self.data.pop(user_id, None)

    def clear(self, user_id: int):
        """
        Clears user's state and data
        """
        self.states.pop(user_id, None)
        self.data.pop(user_id, None)


class FSMCursor:
    def __init__(self, storage: FSMStorage, user_id: int):
        self.storage: FSMStorage = storage
        self.user_id: int = user_id

    def get_state(self) -> Any:
        """
        Gets user's state
        """
        return self.storage.get_state(self.user_id)

    def get_data(self) -> Any:
        """
        Gets user's data
        """
        return self.storage.get_data(self.user_id)

    def change_state(self, new: Any):
        """
        Changes user's state
        """
        self.storage.change_state(self.user_id, new)

    def change_data(self, new: Any):
        """
        Changes user's data
        """
        self.storage.change_data(self.user_id, new)

    def clear_state(self) -> Any:
        """
        Deletes user's state and returns it
        """
        return self.storage.clear_state(self.user_id)

    def clear_data(self) -> Any:
        """
        Deletes user's data and returns it
        """
        return self.storage.clear_data(self.user_id)

    def clear(self):
        """
        Clears user's state and data
        """
        self.storage.clear(self.user_id)
