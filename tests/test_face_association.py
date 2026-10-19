"""用合成人脸框检查一张脸只能归属一个人物；不加载模型，不接触任何照片或设备。"""
from app.faces import FaceEncoder, FaceSample
from app.schemas import Box


def people():
    """两个身体框部分交叠；返回归一化框，供100×100像素的合成脸坐标使用。"""
    return [Box(cls=0, name="person", score=.9, track_id=key, xyxy=coords)
            for key, coords in [(1, (0., 0., .6, 1.)), (2, (.4, 0., 1., 1.))]]


def test_unique_face_anchor_resolves_other_person_without_identity_guess():
    """第一张脸只可能属于人物1，因此交叠区的第二张脸只能属于人物2；不比较身份特征。"""
    first = FaceSample((10, 10, 30, 30), None, "FACE_BLURRED", .99)
    second = FaceSample((45, 10, 55, 30), None, "FACE_BLURRED", .99)
    assigned = FaceEncoder.associate([first, second], people(), 100, 100)
    assert assigned == {1: first, 2: second}


def test_fully_ambiguous_faces_and_extra_faces_remain_unassigned():
    """两张脸都可能属于两个人，或同一个身体框含两张脸时，不能按大小/数组顺序猜归属。"""
    first = FaceSample((45, 10, 55, 30), None, "READY", .99)
    second = FaceSample((46, 10, 56, 30), None, "READY", .99)
    assert FaceEncoder.associate([first, second], people(), 100, 100) == {}
    assert FaceEncoder.associate([first, second], people()[:1], 100, 100) == {}


def test_untracked_person_participates_in_one_to_one_assignment():
    """新白框没有轨迹号也占据它的人脸归属，不能把它的脸抢给旧目标。"""
    boxes = people()
    boxes[1].track_id = None
    first = FaceSample((10, 10, 30, 30), None, "READY", .99)
    second = FaceSample((45, 10, 55, 30), None, "READY", .99)
    assert FaceEncoder.associate([first, second], boxes, 100, 100) == {1: first}
