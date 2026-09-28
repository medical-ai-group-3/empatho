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
    ExamOrderConfirmSerializer,
    ExamOrderHandoffSerializer,
    MeSerializer,
    PushTokenSerializer,
    NotificationSerializer,
    MePatientSerializer,
)
from .nursing import (
    FollowupSerializer,
    VisitCheckInSerializer,
    ExamOrderNoteSerializer,
    FollowupCreateSerializer,
    FollowupCallSerializer,
    FollowupUpdateSerializer,
    PrimaryStaffAssignSerializer,
    PatientPiiCorrectSerializer,
)

from .radiology import (
    StudySerializer,
    # LesionSerializer 는 surgery 것(mesh 포함)을 쓴다 — 아래에서 가져온다.
    # 둘 다 malignancy_p 를 뺀다(화면 비노출)
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
    DiscordanceDetailSerializer,
    SpecimenSerializer,
    LesionSerializer,
    ExamOrderRequestSerializer,
    SurgeryDecisionSerializer,
    ReportExplainSerializer,
    SpecimenBindSerializer,
    DiscordanceDisposeSerializer,
    PrescriptionSerializer,
    PrescriptionCreateSerializer,
)
from .pathology import(
    SpecimenDraftSerializer,
    SpecimenFinalizeSerializer,
    StorageObjectSerializer,
)
from .storage import (
    StorageObjectCancelSerializer,
)
from .personal_note import (
    PersonalNoteSerializer,
    PersonalNoteCreateSerializer,
    PersonalNoteUpdateSerializer,
)
from .prescription import (
    PrescriptionDrugRowSerializer,
    drug_rows,
    PatientPrescriptionSerializer,
    PatientDrugSerializer,
)
