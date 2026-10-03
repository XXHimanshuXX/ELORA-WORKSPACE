from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid
from enum import Enum, auto
from typing import Optional, List, Dict, Any, Callable
import heapq
from datetime import datetime, timedelta


class RuntimeState(Enum):
    IDLE = auto()
    RUNNING = auto()
    WAITING_FOR_APPROVAL = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class BackgroundTask:
    id: str
    goal: str
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    scheduled_at: Optional[float] = None  # For cron-like scheduling
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    dependencies: List[str] = field(default_factory=list)  # Task IDs this depends on


@dataclass
class Session:
    id: str
    goal: str
    state: RuntimeState = RuntimeState.IDLE
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tasks: List[str] = field(default_factory=list)  # Task IDs associated with this session
    background_tasks: List[str] = field(default_factory=list)  # Background task IDs


@dataclass
class ApprovalRequest:
    id: str
    session_id: str
    task_id: str
    description: str
    requested_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    approved: bool = False
    approver: Optional[str] = None
    response: Optional[str] = None


class RuntimeManager:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.background_tasks: Dict[str, BackgroundTask] = {}
        self.approval_requests: Dict[str, ApprovalRequest] = {}
        self.task_queue: List[Tuple[float, TaskPriority, str]] = []  # (timestamp, priority, task_id)
        self._task_counter = 0
        
    def create_session(self, goal: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new agentic session with a specific goal."""
        session_id = f"sess-{int(time.time()*1000)}-{str(uuid.uuid4())[:8]}"
        session = Session(
            id=session_id,
            goal=goal,
            metadata=metadata or {}
        )
        self.sessions[session_id] = session
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve a session by ID."""
        return self.sessions.get(session_id)
    
    def update_session_state(self, session_id: str, state: RuntimeState) -> bool:
        """Update the state of a session."""
        if session_id in self.sessions:
            self.sessions[session_id].state = state
            self.sessions[session_id].updated_at = time.time()
            return True
        return False
    
    def add_task_to_session(self, session_id: str, task_id: str) -> bool:
        """Associate a task with a session."""
        if session_id in self.sessions:
            if task_id not in self.sessions[session_id].tasks:
                self.sessions[session_id].tasks.append(task_id)
            return True
        return False
    
    def submit_background_task(self, 
                              goal: str, 
                              priority: TaskPriority = TaskPriority.NORMAL,
                              scheduled_at: Optional[float] = None,
                              metadata: Optional[Dict[str, Any]] = None,
                              dependencies: Optional[List[str]] = None) -> str:
        """Submit a background task for execution."""
        task_id = f"bg-{int(time.time()*1000)}-{str(uuid.uuid4())[:8]}"
        task = BackgroundTask(
            id=task_id,
            goal=goal,
            priority=priority,
            scheduled_at=scheduled_at,
            metadata=metadata or {},
            dependencies=dependencies or []
        )
        self.background_tasks[task_id] = task
        
        # Add to queue if ready to run (no dependencies or dependencies met)
        if not dependencies or self._dependencies_met(dependencies):
            self._enqueue_task(task_id, priority)
            
        return task_id
    
    def cancel_background_task(self, task_id: str) -> bool:
        """Cancel a background task."""
        if task_id in self.background_tasks:
            task = self.background_tasks[task_id]
            task.state = RuntimeState.CANCELLED
            return True
        return False
    
    def request_approval(self, 
                        session_id: str, 
                        task_id: str, 
                        description: str,
                        expires_in_hours: Optional[int] = 24) -> str:
        """Request approval for a task that requires owner consent."""
        approval_id = f"appr-{int(time.time()*1000)}-{str(uuid.uuid4())[:8]}"
        expires_at = None
        if expires_in_hours:
            expires_at = time.time() + (expires_in_hours * 3600)
            
        approval = ApprovalRequest(
            id=approval_id,
            session_id=session_id,
            task_id=task_id,
            description=description,
            expires_at=expires_at
        )
        self.approval_requests[approval_id] = approval
        return approval_id
    
    def approve_request(self, approval_id: str, approver: str, response: Optional[str] = None) -> bool:
        """Approve a pending approval request."""
        if approval_id in self.approval_requests:
            approval = self.approval_requests[approval_id]
            approval.approved = True
            approval.approver = approver
            approval.response = response
            return True
        return False
    
    def deny_request(self, approval_id: str, approver: str, response: Optional[str] = None) -> bool:
        """Deny a pending approval request."""
        if approval_id in self.approval_requests:
            approval = self.approval_requests[approval_id]
            approval.approved = False
            approval.approver = approver
            approval.response = response
            return True
        return False
    
    def get_pending_approvals(self) -> List[ApprovalRequest]:
        """Get all pending approval requests."""
        now = time.time()
        pending = []
        for approval in self.approval_requests.values():
            if not approval.approved and (approval.expires_at is None or approval.expires_at > now):
                pending.append(approval)
        return sorted(pending, key=lambda x: x.requested_at)
    
    def get_ready_background_tasks(self) -> List[BackgroundTask]:
        """Get background tasks that are ready to execute."""
        ready_tasks = []
        now = time.time()
        
        for task in self.background_tasks.values():
            # Skip if already completed, failed, or cancelled
            if hasattr(task, 'state') and task.state in [RuntimeState.COMPLETED, RuntimeState.FAILED, RuntimeState.CANCELLED]:
                continue
                
            # Check if scheduled time has passed
            if task.scheduled_at and task.scheduled_at > now:
                continue
                
            # Check dependencies
            if task.dependencies and not self._dependencies_met(task.dependencies):
                continue
                
            ready_tasks.append(task)
            
        # Sort by priority and creation time
        ready_tasks.sort(key=lambda t: (-t.priority.value, t.created_at))
        return ready_tasks
    
    def _dependencies_met(self, dependency_ids: List[str]) -> bool:
        """Check if all dependencies for a task are met."""
        for dep_id in dependency_ids:
            if dep_id in self.background_tasks:
                dep_task = self.background_tasks[dep_id]
                # Consider dependency met if task is completed
                if not hasattr(dep_task, 'state') or dep_task.state != RuntimeState.COMPLETED:
                    return False
            # If dependency is not a background task, assume it's external and met
        return True
    
    def _enqueue_task(self, task_id: str, priority: TaskPriority):
        """Add a task to the priority queue."""
        # Use negative timestamp for FIFO within same priority (heapq is min heap)
        entry = (time.time(), priority.value, self._task_counter, task_id)
        heapq.heappush(self.task_queue, entry)
        self._task_counter += 1
    
    def dequeue_task(self) -> Optional[str]:
        """Get the next task from the queue."""
        while self.task_queue:
            _, _, _, task_id = heapq.heappop(self.task_queue)
            # Verify task still exists and is valid
            if task_id in self.background_tasks:
                task = self.background_tasks[task_id]
                # Skip if task is no longer runnable
                if hasattr(task, 'state') and task.state in [RuntimeState.COMPLETED, RuntimeState.FAILED, RuntimeState.CANCELLED]:
                    continue
                return task_id
        return None
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get statistics about current sessions and tasks."""
        now = time.time()
        active_sessions = sum(1 for s in self.sessions.values() if s.state == RuntimeState.RUNNING)
        waiting_approval = len(self.get_pending_approvals())
        ready_bg_tasks = len(self.get_ready_background_tasks())
        
        return {
            "total_sessions": len(self.sessions),
            "active_sessions": active_sessions,
            "pending_approvals": waiting_approval,
            "ready_background_tasks": ready_bg_tasks,
            "queued_tasks": len(self.task_queue),
            "timestamp": now
        }


# Global runtime manager instance
runtime_manager = RuntimeManager()