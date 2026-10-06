package storage

import (
	"context"
	"io"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

// S3 — Garage. S3 호환이라 minio-go 로 붙는다.
//
// Garage 는 리전 개념이 약하지만 서명 계산에 값이 필요하다. conf/garage/garage.toml
// 의 s3_api.s3_region 과 같은 값을 넣어야 SignatureDoesNotMatch 가 안 난다.
type S3 struct {
	cli    *minio.Client
	bucket string
}

func NewS3(endpoint, accessKey, secretKey, bucket, region string, useSSL bool) (*S3, error) {
	c, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
		Region: region,
		// ⚠ path-style 을 강제한다 — 팀 접속 안내서가 못 박은 항목이다.
		//
		//   S3 주소 방식은 두 가지다.
		//     가상 호스트  https://버킷.호스트/키   ← AWS 기본
		//     경로        https://호스트/버킷/키    ← Garage 가 요구
		//
		//   가상 호스트 방식은 버킷 이름이 DNS 로 풀려야 하는데 Garage 는
		//   그런 이름을 안 갖는다. 그러면 주소 자체를 못 찾는다.
		//
		//   minio-go 의 자동 판별이 IP 주소 끝점에서는 경로 방식을 고르지만,
		//   나중에 도메인을 붙이면 판별이 뒤집힐 수 있다. 명시해서 못 박는다.
		BucketLookup: minio.BucketLookupPath,
	})
	if err != nil {
		return nil, err
	}
	return &S3{cli: c, bucket: bucket}, nil
}

func (s *S3) Bucket() string { return s.bucket }

func (s *S3) Put(ctx context.Context, key string, r io.Reader, size int64, ct string) error {
	// size 가 음수면 minio 가 알아서 멀티파트로 올린다.
	_, err := s.cli.PutObject(ctx, s.bucket, key, r, size,
		minio.PutObjectOptions{ContentType: ct})
	return err
}

// Open — minio.Object 는 ReadSeekCloser 다. 그래서 http.ServeContent 에
// 그대로 넘길 수 있고, Range 요청이 저장소까지 그대로 전달된다.
func (s *S3) Open(ctx context.Context, key string) (ReadSeekCloser, *Info, error) {
	o, err := s.cli.GetObject(ctx, s.bucket, key, minio.GetObjectOptions{})
	if err != nil {
		return nil, nil, err
	}
	st, err := o.Stat()
	if err != nil {
		o.Close()
		return nil, nil, err
	}
	return o, &Info{Key: key, Size: st.Size, ContentType: st.ContentType,
		ETag: st.ETag, ModTime: st.LastModified}, nil
}

func (s *S3) Stat(ctx context.Context, key string) (*Info, error) {
	st, err := s.cli.StatObject(ctx, s.bucket, key, minio.StatObjectOptions{})
	if err != nil {
		return nil, err
	}
	return &Info{Key: key, Size: st.Size, ContentType: st.ContentType,
		ETag: st.ETag, ModTime: st.LastModified}, nil
}

func (s *S3) Delete(ctx context.Context, key string) error {
	return s.cli.RemoveObject(ctx, s.bucket, key, minio.RemoveObjectOptions{})
}
