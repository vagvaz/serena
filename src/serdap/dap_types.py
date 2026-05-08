from typing import Any, TypedDict


class DAPMessage(TypedDict, total=False):
    seq: int
    type: str


class DAPRequest(DAPMessage):
    command: str
    arguments: Any


class DAPResponse(DAPMessage):
    request_seq: int
    command: str
    success: bool
    message: str
    body: Any


class DAPEvent(DAPMessage):
    event: str
    body: Any


class Source(TypedDict, total=False):
    name: str
    path: str
    sourceReference: int
    presentationHint: str
    origin: str
    sources: list["Source"]
    adapterData: Any
    checksums: list[dict[str, Any]]


class SourceBreakpoint(TypedDict, total=False):
    line: int
    column: int
    condition: str
    hitCondition: str
    logMessage: str


class Breakpoint(TypedDict, total=False):
    id: int
    verified: bool
    message: str
    source: Source
    line: int
    column: int
    endLine: int
    endColumn: int
    instructionReference: str
    offset: int


class StackFrame(TypedDict, total=False):
    id: int
    name: str
    source: Source
    line: int
    column: int
    endLine: int
    endColumn: int
    canRestart: bool
    instructionPointerReference: str
    moduleId: int
    presentationHint: str


class Scope(TypedDict, total=False):
    name: str
    presentationHint: str
    variablesReference: int
    namedVariables: int
    indexedVariables: int
    expensive: bool
    source: Source
    line: int
    column: int
    endLine: int
    endColumn: int


class Variable(TypedDict, total=False):
    name: str
    value: str
    type: str
    presentationHint: dict[str, str]
    evaluateName: str
    variablesReference: int
    namedVariables: int
    indexedVariables: int
    memoryReference: str


class Thread(TypedDict, total=False):
    id: int
    name: str


class Message(TypedDict, total=False):
    id: int
    format: str
    variables: dict[str, str]
    sendTelemetry: bool
    showUser: bool
    url: str
    urlLabel: str


class Capabilities(TypedDict, total=False):
    supportsConfigurationDoneRequest: bool
    supportsFunctionBreakpoints: bool
    supportsConditionalBreakpoints: bool
    supportsHitConditionalBreakpoints: bool
    supportsEvaluateForHovers: bool
    supportsStepBack: bool
    supportsSetVariable: bool
    supportsRestartFrame: bool
    supportsGotoTargetsRequest: bool
    supportsStepInTargetsRequest: bool
    supportsCompletionsRequest: bool
    supportsModulesRequest: bool
    supportsRestartRequest: bool
    supportsExceptionOptions: bool
    supportsValueFormattingOptions: bool
    supportsExceptionInfoRequest: bool
    supportsTerminateDebuggee: bool
    supportsDelayedStackTraceLoading: bool
    supportsLoadedSourcesRequest: bool
    supportsLogPoints: bool
    supportsTerminateThreadsRequest: bool
    supportsSetExpression: bool
    supportsTerminateRequest: bool
    supportsDataBreakpoints: bool
    supportsReadMemoryRequest: bool
    supportsWriteMemoryRequest: bool
    supportsDisassembleRequest: bool
    supportsCancelRequest: bool
    supportsBreakpointLocationsRequest: bool
    supportsClipboardContext: bool
    supportsSteppingGranularity: bool
    supportsInstructionBreakpoints: bool
    supportsExceptionFilterOptions: bool
    supportsSingleThreadExecutionRequests: bool
