import time
from enum import Enum


class CircuitState(Enum):
  CLOSED = "closed"
  OPEN = "open"
  HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
  pass


class CircuitBreaker:
  def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 30):
    self.failure_threshold = failure_threshold
    self.recovery_timeout = recovery_timeout
    self.failure_count = 0
    self.state = CircuitState.CLOSED
    self.opened_at: float | None = None

  def _can_attempt(self) -> bool:
    if self.state == CircuitState.CLOSED:
      return True

    if self.state == CircuitState.OPEN:
      if self.opened_at and (time.time() - self.opened_at) >= self.recovery_timeout:
        self.state = CircuitState.HALF_OPEN
        return True
      return False

    return True

  def record_success(self) -> None:
    self.failure_count = 0
    self.state = CircuitState.CLOSED
    self.opened_at = None

  def record_failure(self) -> None:
    self.failure_count += 1
    if self.failure_count >= self.failure_threshold:
      self.state = CircuitState.OPEN
      self.opened_at = time.time()

  def before_call(self) -> None:
    if not self._can_attempt():
      raise CircuitBreakerOpenError(
        "Circuit Breaker aberto: Serviço de Estoque indisponível. Tente novamente mais tarde."
      )

  def get_state(self) -> str:
    return self.state.value
