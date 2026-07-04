// Copyright 2026
// Licensed under the Apache License, Version 2.0.

#include <gtest/gtest.h>

#include <cmath>
#include <cstdint>
#include <vector>

#include "standard_robot_pp_ros2/bcp_safety.hpp"

namespace standard_robot_pp_ros2
{
namespace
{

std::vector<uint8_t> makeFrame(bool legacy_add)
{
  std::vector<uint8_t> frame = {0xFF, 0x01, 0x11, 0x04, 0x10, 0x20, 0x30, 0x40};

  uint32_t sum = 0U;
  for (uint8_t byte : frame) {
    sum += byte;
  }
  frame.push_back(static_cast<uint8_t>(sum & 0xFFU));

  uint32_t add = 0U;
  if (legacy_add) {
    uint32_t running = frame[0] + frame[1] + frame[2] + frame[3];
    add = running;
    for (size_t i = 4U; i < frame.size() - 1U; ++i) {
      running += frame[i];
      add += running;
    }
  } else {
    uint32_t running = 0U;
    for (size_t i = 0U; i < frame.size() - 1U; ++i) {
      running += frame[i];
      add += running;
    }
  }
  frame.push_back(static_cast<uint8_t>(add & 0xFFU));
  return frame;
}

TEST(BcpChecksum, AcceptsStandardAndLegacyAddChecks)
{
  EXPECT_EQ(verifyBcpChecksums(makeFrame(false)), BcpChecksumResult::STANDARD);
  EXPECT_EQ(verifyBcpChecksums(makeFrame(true)), BcpChecksumResult::LEGACY);
}

TEST(BcpChecksum, RejectsCorruption)
{
  auto bad_sum = makeFrame(false);
  bad_sum[4] ^= 0x01U;
  EXPECT_EQ(verifyBcpChecksums(bad_sum), BcpChecksumResult::INVALID_SUM);

  auto bad_add = makeFrame(false);
  bad_add.back() ^= 0x01U;
  EXPECT_EQ(verifyBcpChecksums(bad_add), BcpChecksumResult::INVALID_ADD);
}

TEST(OdomAxisInversion, ConvertsMeasuredCBoardSignsToRosRep103)
{
  CBoardOdomSample cboard;
  cboard.x = 1.0;
  cboard.y = 2.0;
  cboard.yaw = 0.3;
  cboard.vx = 4.0;
  cboard.vy = 5.0;
  cboard.wz = 0.6;

  const auto ros = applyOdomAxisInversion(cboard, true, true, true);
  EXPECT_DOUBLE_EQ(ros.x, -1.0);
  EXPECT_DOUBLE_EQ(ros.y, -2.0);
  EXPECT_DOUBLE_EQ(ros.yaw, -0.3);
  EXPECT_DOUBLE_EQ(ros.vx, -4.0);
  EXPECT_DOUBLE_EQ(ros.vy, -5.0);
  EXPECT_DOUBLE_EQ(ros.wz, -0.6);
}

TEST(OdomGuard, PassesNormalCBoardPoseWithoutIntegratingTwist)
{
  OdomGuard guard;
  CBoardOdomSample first;
  first.x = 1.0;
  first.y = 2.0;
  first.yaw = 0.2;

  const auto first_result = guard.process(first, 1000);
  ASSERT_TRUE(first_result.accepted);
  EXPECT_DOUBLE_EQ(first_result.sample.x, 1.0);
  EXPECT_DOUBLE_EQ(first_result.sample.y, 2.0);
  EXPECT_DOUBLE_EQ(first_result.sample.yaw, 0.2);

  CBoardOdomSample second = first;
  second.vx = 0.5;
  second.x = 1.01;
  const auto second_result = guard.process(second, 1025);
  ASSERT_TRUE(second_result.accepted);
  EXPECT_DOUBLE_EQ(second_result.sample.x, 1.01);
}

TEST(OdomGuard, RejectsImpossiblePositionAndVelocity)
{
  OdomGuard guard;
  ASSERT_TRUE(guard.process(CBoardOdomSample{}, 1000).accepted);

  CBoardOdomSample jump;
  jump.x = 20.0;
  auto result = guard.process(jump, 1025);
  EXPECT_FALSE(result.accepted);
  EXPECT_EQ(result.reason, OdomRejectReason::POSITION_JUMP);

  CBoardOdomSample too_fast;
  too_fast.vx = 20.0;
  result = guard.process(too_fast, 1050);
  EXPECT_FALSE(result.accepted);
  EXPECT_EQ(result.reason, OdomRejectReason::LINEAR_SPEED_RANGE);
}

TEST(OdomGuard, PreservesWorldPoseAcrossConfirmedCBoardReset)
{
  OdomGuardConfig config;
  config.reset_confirm_frames = 3U;
  config.reset_gap_ms = 10000;
  OdomGuard guard(config);

  CBoardOdomSample before_reset;
  before_reset.x = 5.0;
  before_reset.y = 2.0;
  before_reset.yaw = 1.0;
  ASSERT_TRUE(guard.process(before_reset, 1000).accepted);

  CBoardOdomSample reset_sample;
  EXPECT_FALSE(guard.process(reset_sample, 1025).accepted);
  reset_sample.x = 0.01;
  EXPECT_FALSE(guard.process(reset_sample, 1050).accepted);
  reset_sample.x = 0.02;
  const auto reset_result = guard.process(reset_sample, 1075);
  ASSERT_TRUE(reset_result.accepted);
  ASSERT_TRUE(reset_result.reset_compensated);
  EXPECT_NEAR(reset_result.sample.x, 5.0, 1e-9);
  EXPECT_NEAR(reset_result.sample.y, 2.0, 1e-9);
  EXPECT_NEAR(reset_result.sample.yaw, 1.0, 1e-9);

  CBoardOdomSample after_reset = reset_sample;
  after_reset.x = 0.12;
  const auto after_result = guard.process(after_reset, 1100);
  ASSERT_TRUE(after_result.accepted);
  EXPECT_NEAR(after_result.sample.x, 5.0 + 0.10 * std::cos(1.0), 1e-9);
  EXPECT_NEAR(after_result.sample.y, 2.0 + 0.10 * std::sin(1.0), 1e-9);
}

}  // namespace
}  // namespace standard_robot_pp_ros2
