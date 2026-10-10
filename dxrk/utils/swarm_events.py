# SPDX-License-Identifier: MIT
"""Swarm event bus."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from dxrk.utils.swarm_model import EventHandler, SwarmEvent, SwarmEventType, _Context, _with_cancel


class EventBus:
    """Dispatches swarm events to subscribed handlers. Mirrors swarm.EventBus.

    Drop policy: the event channel is bounded (1024). When full,
    :meth:`Publish` drops the new event and increments a counter readable
    via :meth:`DroppedCount` — drops are explicit, never silent.
    """

    def __init__(self, ctx: _Context | None = None) -> None:
        self._handlers: dict[SwarmEventType, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._mu = threading.RLock()
        self._ctx, self._cancel = _with_cancel(ctx)
        self._thread: threading.Thread | None = None
        self._event_ch: queue.Queue[SwarmEvent] = queue.Queue(maxsize=1024)
        self._closed = False
        self._dropped = 0

    def DroppedCount(self) -> int:
        """Return the number of events dropped due to a full channel."""
        with self._mu:
            return self._dropped

    def Subscribe(self, event_type: SwarmEventType, handler: EventHandler) -> Callable[[], None]:
        """Subscribe a handler to one event type. Mirrors EventBus.Subscribe().

        The returned callable removes exactly this registration (matched by
        identity), so it stays correct under concurrent subscribe/unsubscribe.
        """
        with self._mu:
            self._handlers.setdefault(event_type, []).append(handler)

            def unsubscribe() -> None:
                with self._mu:
                    handlers = self._handlers.get(event_type, [])
                    for i, h in enumerate(handlers):
                        if h is handler:
                            del handlers[i]
                            break

            return unsubscribe

    def Unsubscribe(self, event_type: SwarmEventType, handler: EventHandler) -> bool:
        """Remove one registration of ``handler`` for ``event_type``.

        Returns True when a registration was removed.
        """
        with self._mu:
            handlers = self._handlers.get(event_type, [])
            for i, h in enumerate(handlers):
                if h is handler:
                    del handlers[i]
                    return True
            for i, h in enumerate(self._all_handlers):
                if h is handler:
                    del self._all_handlers[i]
                    return True
            return False

    def SubscribeAll(self, handler: EventHandler) -> Callable[[], None]:
        """Subscribe a handler to every event type, present and future.

        The handler is kept in a dedicated catch-all list consulted on
        every dispatch, so types registered after subscribing are covered,
        and each event reaches the handler exactly once.
        """
        with self._mu:
            self._all_handlers.append(handler)

            def unsubscribe() -> None:
                with self._mu:
                    for i, h in enumerate(self._all_handlers):
                        if h is handler:
                            del self._all_handlers[i]
                            break

            return unsubscribe

    def Publish(self, event: SwarmEvent) -> None:
        """Publish an event to the bus. Mirrors EventBus.Publish().

        When the bounded channel is full the event is dropped and the
        :meth:`DroppedCount` counter is incremented.
        """
        with self._mu:
            if self._closed:
                return
        try:
            self._event_ch.put_nowait(event)
        except queue.Full:
            with self._mu:
                self._dropped += 1

    def Start(self) -> None:
        """Start the event processing goroutine. Mirrors EventBus.Start()."""
        self._thread = threading.Thread(target=self._process_events, daemon=True)
        self._thread.start()

    def _process_events(self) -> None:
        while True:
            try:
                event = self._event_ch.get(timeout=0.05)
            except queue.Empty:
                if self._ctx.err() is not None:
                    return
                continue
            self._dispatch(event)

    def _dispatch(self, event: SwarmEvent) -> None:
        with self._mu:
            handlers = list(self._handlers.get(event.type, []))
            catch_all = list(self._all_handlers)
        for h in handlers:
            h(event)
        for h in catch_all:
            h(event)

    def Stop(self) -> None:
        """Stop the event bus. Mirrors EventBus.Stop()."""
        with self._mu:
            if self._closed:
                return
            self._closed = True
        self._cancel()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def Len(self) -> int:
        """Return the total number of registered handlers. Mirrors EventBus.Len()."""
        with self._mu:
            return sum(len(hs) for hs in self._handlers.values()) + len(self._all_handlers)


def NewEventBus(ctx: _Context | None = None) -> EventBus:
    """Create a new event bus. Mirrors swarm.NewEventBus()."""
    return EventBus(ctx)
