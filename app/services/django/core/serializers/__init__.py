"""serializers 패키지 — 부서별 파일로 나누고 여기서 재수출한다.

기존 코드가 `from . import serializers` 후 `serializers.PatientSerializer`
식으로 쓰던 걸 그대로 유지하기 위한 것이다.
"""

from .reception import (
    PatientPiiSerializer,
    PatientSerializer,
    PatientDetailSerializer,
    ExamOrderSerializer,
    PatientExamOrderSerializer,
    PatientListSerializer,
    PatientCreateSerializer,
    ExamOrderItemSerializer,
    ReservationCreateSerializer,
    ReservationRequestCreateSerializer,
    StaffSerializer,
    PatientRegisterSerializer,
    CheckInSerializer,
    ExamOrderScheduleSerializer,
    MeSerializer,
)
from .nursing import (
    FollowupSerializer,
    VisitCheckInSerializer,
    FollowupCreateSerializer,
    FollowupCallSerializer,
    PrimaryStaffAssignSerializer,
)

from .radiology import (
    StudySerializer,
    LesionSerializer,
    AssessmentSerializer,
    AiResultSerializer,
    StorageObjectSerializer,
    AssessmentDraftSerializer,
    StudyUploadReviewSerializer,
    LesionCreateSerializer,
    LesionFalsePositiveSerializer,
    AssessmentAmendSerializer,
)

from .surgery import (
    ReportSerializer,
    DiscordanceFlagSerializer,
    SpecimenSerializer,
    LesionSerializer,
    ExamOrderRequestSerializer,
    SurgeryDecisionSerializer,
    ReportExplainSerializer,
    SpecimenBindSerializer,
    DiscordanceDisposeSerializer
)
from .pathology import(
    SpecimenDraftSerializer,
    SpecimenFinalizeSerializer,
    SpecimenAmendSerializer,
    StorageObjectSerializer,
)