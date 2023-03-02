import unittest
from datetime import datetime, timezone
from typing import Iterator

from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from grpc import StatusCode
from grpc_testing import server_from_dictionary, strict_real_time

from pynumaflow._constants import DATUM_KEY
from pynumaflow.function import (
    Message,
    Messages,
    MessageT,
    MessageTs,
    Datum,
    Metadata,
)
from pynumaflow.function._dtypes import DROP
from pynumaflow.function.proto import udfunction_pb2
from pynumaflow.function.server import UserDefinedFunctionServicer


def map_handler(key: str, datum: Datum) -> Messages:
    val = datum.value
    msg = "payload:%s event_time:%s watermark:%s" % (
        val.decode("utf-8"),
        datum.event_time,
        datum.watermark,
    )
    val = bytes(msg, encoding="utf-8")
    messages = Messages()
    messages.append(Message.to_vtx(key, val))
    return messages


def mapt_handler(key: str, datum: Datum) -> MessageTs:
    val = datum.value
    msg = "payload:%s event_time:%s watermark:%s" % (
        val.decode("utf-8"),
        datum.event_time,
        datum.watermark,
    )
    val = bytes(msg, encoding="utf-8")
    messagets = MessageTs()
    messagets.append(MessageT.to_vtx(key, val, mock_new_event_time()))
    return messagets


async def reduce_handler(key: str, datums: Iterator[Datum], md: Metadata) -> Messages:
    interval_window = md.interval_window
    counter = 0
    async for _ in datums:
        counter += 1
    msg = (
        f"counter:{counter} interval_window_start:{interval_window.start} "
        f"interval_window_end:{interval_window.end}"
    )
    return Messages(Message.to_vtx(key, str.encode(msg)))


def err_map_handler(_: str, __: Datum) -> Messages:
    raise RuntimeError("Something is fishy!")


def err_mapt_handler(_: str, __: Datum) -> MessageTs:
    raise RuntimeError("Something is fishy!")


def err_reduce_handler(_: str, __: Iterator[Datum], ___: Metadata) -> Messages:
    raise RuntimeError("Something is fishy!")


def mock_message():
    msg = bytes("test_mock_message", encoding="utf-8")
    return msg


def mock_event_time():
    t = datetime.fromtimestamp(1662998400, timezone.utc)
    return t


def mock_new_event_time():
    t = datetime.fromtimestamp(1663098400, timezone.utc)
    return t


def mock_watermark():
    t = datetime.fromtimestamp(1662998460, timezone.utc)
    return t


def mock_interval_window_start():
    return 1662998400000


def mock_interval_window_end():
    return 1662998460000


class TestServer(unittest.TestCase):
    def setUp(self) -> None:
        my_servicer = UserDefinedFunctionServicer(
            map_handler=map_handler, mapt_handler=mapt_handler, reduce_handler=reduce_handler
        )
        services = {udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"]: my_servicer}
        self.test_server = server_from_dictionary(services, strict_real_time())

    def test_init_with_args(self) -> None:
        my_servicer = UserDefinedFunctionServicer(
            map_handler=map_handler,
            mapt_handler=mapt_handler,
            reduce_handler=reduce_handler,
            sock_path="/tmp/test.sock",
            max_message_size=1024 * 1024 * 5,
        )
        self.assertEqual(my_servicer.sock_path, "unix:///tmp/test.sock")
        self.assertEqual(my_servicer._max_message_size, 1024 * 1024 * 5)

    def test_udf_map_err(self):
        my_servicer = UserDefinedFunctionServicer(map_handler=err_map_handler)
        services = {udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"]: my_servicer}
        self.test_server = server_from_dictionary(services, strict_real_time())

        event_time_timestamp = _timestamp_pb2.Timestamp()
        event_time_timestamp.FromDatetime(dt=mock_event_time())
        watermark_timestamp = _timestamp_pb2.Timestamp()
        watermark_timestamp.FromDatetime(dt=mock_watermark())

        request = udfunction_pb2.Datum(
            value=mock_message(),
            event_time=udfunction_pb2.EventTime(event_time=event_time_timestamp),
            watermark=udfunction_pb2.Watermark(watermark=watermark_timestamp),
        )

        method = self.test_server.invoke_unary_unary(
            method_descriptor=(
                udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"].methods_by_name[
                    "MapFn"
                ]
            ),
            invocation_metadata={
                (DATUM_KEY, "test"),
                ("this_metadata_will_be_skipped", "test_ignore"),
            },
            request=request,
            timeout=1,
        )

        response, metadata, code, details = method.termination()
        self.assertEqual(1, len(response.elements))
        self.assertEqual(DROP.decode(), response.elements[0].key)
        self.assertEqual(
            b"",
            response.elements[0].value,
        )

    def test_udf_mapt_err(self):
        my_servicer = UserDefinedFunctionServicer(mapt_handler=err_mapt_handler)
        services = {udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"]: my_servicer}
        self.test_server = server_from_dictionary(services, strict_real_time())

        event_time_timestamp = _timestamp_pb2.Timestamp()
        event_time_timestamp.FromDatetime(dt=mock_event_time())
        watermark_timestamp = _timestamp_pb2.Timestamp()
        watermark_timestamp.FromDatetime(dt=mock_watermark())

        request = udfunction_pb2.Datum(
            value=mock_message(),
            event_time=udfunction_pb2.EventTime(event_time=event_time_timestamp),
            watermark=udfunction_pb2.Watermark(watermark=watermark_timestamp),
        )

        method = self.test_server.invoke_unary_unary(
            method_descriptor=(
                udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"].methods_by_name[
                    "MapTFn"
                ]
            ),
            invocation_metadata={
                (DATUM_KEY, "test"),
                ("this_metadata_will_be_skipped", "test_ignore"),
            },
            request=request,
            timeout=1,
        )

        response, metadata, code, details = method.termination()
        self.assertEqual(1, len(response.elements))
        self.assertEqual(DROP.decode(), response.elements[0].key)
        self.assertEqual(
            b"",
            response.elements[0].value,
        )

    def test_is_ready(self):
        method = self.test_server.invoke_unary_unary(
            method_descriptor=(
                udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"].methods_by_name[
                    "IsReady"
                ]
            ),
            invocation_metadata={DATUM_KEY, "test"},
            request=_empty_pb2.Empty(),
            timeout=1,
        )

        response, metadata, code, details = method.termination()
        expected = udfunction_pb2.ReadyResponse(ready=True)
        self.assertEqual(expected, response)
        self.assertEqual(code, StatusCode.OK)

    def test_map_forward_message(self):
        event_time_timestamp = _timestamp_pb2.Timestamp()
        event_time_timestamp.FromDatetime(dt=mock_event_time())
        watermark_timestamp = _timestamp_pb2.Timestamp()
        watermark_timestamp.FromDatetime(dt=mock_watermark())

        request = udfunction_pb2.Datum(
            value=mock_message(),
            event_time=udfunction_pb2.EventTime(event_time=event_time_timestamp),
            watermark=udfunction_pb2.Watermark(watermark=watermark_timestamp),
        )

        method = self.test_server.invoke_unary_unary(
            method_descriptor=(
                udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"].methods_by_name[
                    "MapFn"
                ]
            ),
            invocation_metadata={
                (DATUM_KEY, "test"),
                ("this_metadata_will_be_skipped", "test_ignore"),
            },
            request=request,
            timeout=1,
        )

        response, metadata, code, details = method.termination()
        self.assertEqual(1, len(response.elements))
        self.assertEqual("test", response.elements[0].key)
        self.assertEqual(
            bytes(
                "payload:test_mock_message "
                "event_time:2022-09-12 16:00:00 watermark:2022-09-12 16:01:00",
                encoding="utf-8",
            ),
            response.elements[0].value,
        )
        self.assertEqual(code, StatusCode.OK)

    def test_mapt_assign_new_event_time(self):
        event_time_timestamp = _timestamp_pb2.Timestamp()
        event_time_timestamp.FromDatetime(dt=mock_event_time())
        watermark_timestamp = _timestamp_pb2.Timestamp()
        watermark_timestamp.FromDatetime(dt=mock_watermark())

        request = udfunction_pb2.Datum(
            value=mock_message(),
            event_time=udfunction_pb2.EventTime(event_time=event_time_timestamp),
            watermark=udfunction_pb2.Watermark(watermark=watermark_timestamp),
        )

        method = self.test_server.invoke_unary_unary(
            method_descriptor=(
                udfunction_pb2.DESCRIPTOR.services_by_name["UserDefinedFunction"].methods_by_name[
                    "MapTFn"
                ]
            ),
            invocation_metadata={
                (DATUM_KEY, "test"),
                ("this_metadata_will_be_skipped", "test_ignore"),
            },
            request=request,
            timeout=1,
        )

        response, metadata, code, details = method.termination()
        self.assertEqual(1, len(response.elements))
        self.assertEqual("test", response.elements[0].key)
        self.assertEqual(
            bytes(
                "payload:test_mock_message "
                "event_time:2022-09-12 16:00:00 watermark:2022-09-12 16:01:00",
                encoding="utf-8",
            ),
            response.elements[0].value,
        )
        # Verify new event time gets assigned.
        updated_event_time_timestamp = _timestamp_pb2.Timestamp()
        updated_event_time_timestamp.FromDatetime(dt=mock_new_event_time())
        self.assertEqual(udfunction_pb2.EventTime(event_time=updated_event_time_timestamp),
                         response.elements[0].event_time)
        self.assertEqual(code, StatusCode.OK)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            UserDefinedFunctionServicer()

    def test_invalid_reduce_metadata(self) -> None:
        try:
            _ = self.test_server.invoke_stream_unary(
                method_descriptor=(
                    udfunction_pb2.DESCRIPTOR.services_by_name[
                        "UserDefinedFunction"
                    ].methods_by_name["ReduceFn"]
                ),
                invocation_metadata={},
                timeout=1,
            )
        except Exception as err:
            self.assertEqual(
                "Expected to have key/window_start_time/window_end_time but got empty value.",
                err.__str__,
            )


if __name__ == "__main__":
    unittest.main()
