# SPDX-License-Identifier: MIT
"""Swarm event bus."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from dxrk.utils.swarm_model import EventHandler as EventHandler
from dxrk.utils.swarm_model import SwarmEvent as SwarmEvent
from dxrk.utils.swarm_model import SwarmEventType as SwarmEventType
from dxrk.utils.swarm_model import _Context as _Context
from dxrk.utils.swarm_model import _with_cancel as _with_cancel


class EventBus:
    """Dispatches swarm events to subscribed handlers. Mirrors swarm.EventBus."""

    def __init__(self, ctx: _Context | None = None) -> None:
        self._handlers: dict[SwarmEventType, list[EventHandler]] = {}
        self._mu = threading.RLock()
        self._ctx, self._cancel = _with_cancel(ctx)
        self._thread: threading.Thread | None = None
        self._event_ch: queue.Queue[SwarmEvent] = queue.Queue(maxsize=1024)
        self._closed = False

    def Subscribe(self, event_type: SwarmEventType, handler: EventHandler) -> Callable[[], None]:
        """Subscribe a handler to one event type. Mirrors EventBus.Subscribe()."""
        with self._mu:
            self._handlers.setdefault(event_type, []).append(handler)
            index = len(self._handlers[event_type]) - 1
            target = self._handlers[event_type]

            def unsubscribe() -> None:
                with self._mu:
                    if index < len(target):
                        del target[index]

            return unsubscribe

    def SubscribeAll(self, handler: EventHandler) -> Callable[[], None]:
        """Subscribe a handler to every existing event type. Mirrors EventBus.SubscribeAll()."""
        with self._mu:
            for event_type in list(self._handlers):
                self._handlers[event_type].append(handler)

            def unsubscribe() -> None:
                with self._mu:
                    for event_type in list(self._handlers):
                        handlers = self._handlers[event_type]
                        for i, h in enumerate(handlers):
                            if h is handler:
                                del handlers[i]
                                break

            return unsubscribe

    def Publish(self, event: SwarmEvent) -> None:
        """Publish an event to the bus. Mirrors EventBus.Publish()."""
        with self._mu:
            if self._closed:
                return
        try:
            self._event_ch.put_nowait(event)
        except queue.Full:
            pass

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
            all_handlers: list[EventHandler] = []
            for hs in self._handlers.values():
                all_handlers.extend(hs)
        for h in handlers:
            h(event)
        for h in all_handlers:
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
            return sum(len(hs) for hs in self._handlers.values())


def NewEventBus(ctx: _Context | None = None) -> EventBus:
    """Create a new event bus. Mirrors swarm.NewEventBus()."""
    return EventBus(ctx)
